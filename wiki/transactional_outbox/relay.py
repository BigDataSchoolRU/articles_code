# confluent-kafka 2.16.1, psycopg 3.3.8, Kafka 4.3.2, PostgreSQL 18.6, прогнано на стенде 2026-11-06
"""Polling publisher: ретранслятор outbox в Kafka опросом таблицы.

Каждая пачка идёт одной транзакцией: забрать строки с FOR UPDATE SKIP LOCKED, отправить,
дождаться подтверждения брокера, отметить published_at, COMMIT. Падение между отправкой и
COMMIT откатывает отметку, и строки уходят повторно: доставка «как минимум один раз».
"""
import json
import os
import time

import psycopg
from confluent_kafka import Producer

PG_DSN = os.environ.get("PG_DSN", "postgresql://demo:demo@127.0.0.1:55438/shop")
KAFKA = os.environ.get("KAFKA_BOOTSTRAP", "127.0.0.1:59092")

# SKIP LOCKED: второй экземпляр ретранслятора не ждёт чужую пачку, а берёт следующие строки
FETCH_BATCH = """
SELECT id, aggregatetype, aggregateid, type, payload
  FROM outbox
 WHERE published_at IS NULL
 ORDER BY created_at
 LIMIT %s
   FOR UPDATE SKIP LOCKED
"""


class RelayCrash(Exception):
    """Имитация падения процесса ретранслятора."""


def make_producer(client_id: str) -> Producer:
    # acks=all и идемпотентный продюсер: брокер не задвоит сообщение при ретраях внутри сессии,
    # но от повтора после рестарта самого ретранслятора это не спасает
    return Producer({
        "bootstrap.servers": KAFKA,
        "client.id": client_id,
        "acks": "all",
        "enable.idempotence": True,
        "linger.ms": 5,
    })


def relay_batch(conn, producer, topic_prefix: str, batch_size: int = 10,
                crash_after_produce: bool = False, before_produce=None) -> int:
    """Одна пачка outbox -> Kafka. Возвращает число отправленных событий.

    before_produce вызывается после захвата строк и до отправки: в демо им имитируется пауза
    ретранслятора (сборка мусора, сеть), пока строки пачки уже заблокированы.
    """
    with conn.transaction():
        rows = conn.execute(FETCH_BATCH, (batch_size,)).fetchall()
        if not rows:
            return 0
        if before_produce is not None:
            before_produce(rows)
        errors = []

        def on_delivery(err, _msg):
            if err is not None:
                errors.append(err)

        for event_id, agg_type, agg_id, event_type, payload in rows:
            producer.produce(
                f"{topic_prefix}.{agg_type}",
                key=agg_id,  # ключ агрегата: все события заказа в одной партиции
                value=json.dumps(payload, ensure_ascii=False),
                headers=[("id", str(event_id)), ("eventType", event_type)],
                on_delivery=on_delivery,
            )
        # ждём подтверждения брокера до отметки строк, иначе отметка может опередить потерю
        if producer.flush(15) > 0 or errors:
            raise RuntimeError(f"брокер не подтвердил пачку: {errors[:1]}")
        if crash_after_produce:
            # сообщения уже в Kafka, а UPDATE ещё не выполнен: транзакция откатится
            raise RelayCrash("ретранслятор упал после отправки и до отметки строк")
        conn.execute("UPDATE outbox SET published_at = now() WHERE id = ANY(%s)",
                     ([r[0] for r in rows],))
    return len(rows)


def run_relay(name: str, topic_prefix: str, batch_size: int = 10,
              idle_exit: float = 1.0, poll_interval: float = 0.2) -> dict:
    """Крутит пачки, пока outbox пуст дольше idle_exit секунд. Возвращает счётчики."""
    producer = make_producer(name)
    stats = {"relay": name, "batches": 0, "events": 0}
    with psycopg.connect(PG_DSN, autocommit=True) as conn:
        idle_since = None
        while True:
            sent = relay_batch(conn, producer, topic_prefix, batch_size)
            if sent:
                stats["batches"] += 1
                stats["events"] += sent
                idle_since = None
                continue
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since > idle_exit:
                return stats
            time.sleep(poll_interval)


if __name__ == "__main__":
    import sys
    prefix = sys.argv[1] if len(sys.argv) > 1 else "polling.event"
    print(run_relay("relay-cli", prefix))
