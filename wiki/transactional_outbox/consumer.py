# confluent-kafka 2.16.1, psycopg 3.3.8, Kafka 4.3.2, PostgreSQL 18.6, прогнано на стенде 2026-11-06
"""Консьюмеры сервиса лояльности: наивный и с таблицей inbox.

Эффект события OrderCreated: начислить покупателю баллы, 1 балл за каждые 100 рублей.
Наивный консьюмер применяет эффект на каждое сообщение и задваивает баллы на повторах.
Консьюмер с inbox вставляет id события в loyalty.inbox и начисляет баллы в одной транзакции:
повтор упирается в первичный ключ и эффект не применяется второй раз.
"""
import json
import os
import time
import uuid

import psycopg
from confluent_kafka import Consumer, KafkaException, OFFSET_BEGINNING, TopicPartition

PG_DSN = os.environ.get("PG_DSN", "postgresql://demo:demo@127.0.0.1:55438/shop")
KAFKA = os.environ.get("KAFKA_BOOTSTRAP", "127.0.0.1:59092")

ADD_POINTS = """
INSERT INTO loyalty.points (customer, points) VALUES (%s, %s)
ON CONFLICT (customer) DO UPDATE SET points = loyalty.points.points + EXCLUDED.points
"""


def _decode(msg) -> dict:
    headers = {k: (v.decode() if v is not None else None) for k, v in (msg.headers() or [])}
    value = msg.value()
    return {
        "partition": msg.partition(),
        "offset": msg.offset(),
        "key": msg.key().decode() if msg.key() is not None else None,
        "headers": headers,
        "value": json.loads(value) if value else None,
    }


def _partitions(consumer, topic: str) -> list[int]:
    md = consumer.list_topics(topic, timeout=10)
    return sorted(md.topics[topic].partitions)


def _high_watermark(consumer, topic: str, p: int) -> int:
    # у только что созданного топика лидер партиции выбирается не сразу: NOT_LEADER, пробуем ещё
    for attempt in range(20):
        try:
            return consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=10)[1]
        except KafkaException:
            if attempt == 19:
                raise
            time.sleep(0.5)


def _read_until_end(consumer, topic: str, starts: dict[int, int], timeout: float) -> list:
    """Читает назначенные партиции до верхней границы, снятой в момент вызова."""
    highs = {p: _high_watermark(consumer, topic, p) for p in starts}
    consumer.assign([TopicPartition(topic, p, off) for p, off in starts.items()])
    done = {p for p in starts if highs[p] == 0 or (starts[p] >= 0 and starts[p] >= highs[p])}
    out, deadline = [], time.monotonic() + timeout
    while len(done) < len(starts) and time.monotonic() < deadline:
        msg = consumer.poll(0.5)
        if msg is None or msg.error():
            continue
        out.append(msg)
        if msg.offset() + 1 >= highs[msg.partition()]:
            done.add(msg.partition())
    return out


def read_topic(topic: str, timeout: float = 20.0) -> list[dict]:
    """Все сообщения топика с начала, без группы и без коммитов: для подсчётов в демо."""
    c = Consumer({"bootstrap.servers": KAFKA, "group.id": f"reader-{uuid.uuid4()}",
                  "enable.auto.commit": False})
    try:
        parts = _partitions(c, topic)
        msgs = _read_until_end(c, topic, {p: OFFSET_BEGINNING for p in parts}, timeout)
        return [_decode(m) for m in msgs]
    finally:
        c.close()


def _group_consumer(group: str):
    return Consumer({"bootstrap.servers": KAFKA, "group.id": group,
                     "enable.auto.commit": False, "auto.offset.reset": "earliest"})


def _group_starts(c, topic: str) -> dict[int, int]:
    # с последнего закоммиченного оффсета группы, а если его нет, то с начала
    committed = c.committed([TopicPartition(topic, p) for p in _partitions(c, topic)], timeout=10)
    return {tp.partition: (tp.offset if tp.offset >= 0 else OFFSET_BEGINNING) for tp in committed}


def consume_naive(topic: str, group: str) -> dict:
    """Начисляет баллы на каждое сообщение, без проверки повторов."""
    c = _group_consumer(group)
    stats = {"messages": 0, "applied": 0}
    try:
        msgs = _read_until_end(c, topic, _group_starts(c, topic), 20.0)
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            for msg in msgs:
                ev = _decode(msg)
                stats["messages"] += 1
                if ev["headers"].get("eventType") != "OrderCreated":
                    continue
                with conn.transaction():
                    conn.execute(ADD_POINTS, (ev["value"]["customer"], int(ev["value"]["amount"]) // 100))
                stats["applied"] += 1
                c.commit(message=msg, asynchronous=False)
    finally:
        c.close()
    return stats


def consume_with_inbox(topic: str, group: str, crash_before_offset_commit: bool = False) -> dict:
    """Идемпотентный консьюмер: inbox и эффект в одной транзакции, оффсет коммитится после неё."""
    c = _group_consumer(group)
    stats = {"messages": 0, "applied": 0, "skipped": 0}
    try:
        msgs = _read_until_end(c, topic, _group_starts(c, topic), 20.0)
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            for msg in msgs:
                ev = _decode(msg)
                stats["messages"] += 1
                with conn.transaction():
                    # id события из заголовка: его ставит и наш ретранслятор, и Debezium Outbox Event Router
                    cur = conn.execute(
                        "INSERT INTO loyalty.inbox (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
                        (ev["headers"]["id"],))
                    if cur.rowcount == 0:
                        stats["skipped"] += 1  # уже обработано: эффект не повторяем
                    else:
                        if ev["headers"].get("eventType") == "OrderCreated":
                            conn.execute(ADD_POINTS, (ev["value"]["customer"],
                                                      int(ev["value"]["amount"]) // 100))
                        stats["applied"] += 1
                if crash_before_offset_commit:
                    continue  # процесс «упадёт» после транзакции в БД, оффсет в Kafka не сдвинут
                c.commit(message=msg, asynchronous=False)
    finally:
        c.close()
    return stats
