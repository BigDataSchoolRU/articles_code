# confluent-kafka 2.16.1 (librdkafka 2.16.0), apache/kafka 4.3.2 KRaft, SQLite 3.45.1, прогнано на стенде 2026-11-14
"""Потоковая джоба Kappa: читает лог заказов и держит выручку по клиентам в serving-таблице.

Одна и та же программа в двух версиях логики:
  v1 — исходная, с ошибкой: возврат прибавляется к выручке, как продажа;
  v2 — исправленная: возврат вычитается.
У каждой версии своя consumer group и своя таблица orders_by_customer_<версия>. Новая группа не имеет
сохранённых offset'ов и по auto.offset.reset=earliest читает лог с самого начала, это и есть пересчёт.
"""
import argparse
import json
import os
import sqlite3
import time
from collections import defaultdict

from confluent_kafka import OFFSET_INVALID, Consumer, KafkaException, TopicPartition

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "127.0.0.1:59093")
TOPIC = "kappa_architecture_orders"


def delta_v1(ev: dict) -> int:
    return ev["amount_cents"]  # ошибка v1: тип события не смотрим, возврат прибавляется


def delta_v2(ev: dict) -> int:
    return ev["amount_cents"] if ev["type"] == "order" else -ev["amount_cents"]


LOGIC = {"v1": delta_v1, "v2": delta_v2}


def open_serving(path: str, table: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")  # приложение читает, пока джобы пишут
    db.execute(f"CREATE TABLE IF NOT EXISTS {table} ("
               "customer_id TEXT PRIMARY KEY, revenue_cents INTEGER NOT NULL, events INTEGER NOT NULL)")
    return db


def lag(consumer: Consumer) -> int:
    # лаг = голова лога (high watermark) минус позиция джобы, по всем её партициям
    total = 0
    for tp in consumer.assignment():
        low, high = consumer.get_watermark_offsets(tp, timeout=5, cached=False)
        pos = consumer.position([tp])[0].offset
        if pos == OFFSET_INVALID:  # из партиции ещё ничего не прочитано
            committed = consumer.committed([tp], timeout=5)[0].offset
            pos = committed if committed >= 0 else low
        total += high - pos
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=sorted(LOGIC), required=True)
    ap.add_argument("--db", default="serving.db")
    ap.add_argument("--exit-when-caught-up", action="store_true", help="выйти, как только лаг стал нулевым")
    ap.add_argument("--caught-up-lag", type=int, default=0,
                    help="лаг, при котором джоба считается догнавшей: при живом потоке ровно 0 бывает редко")
    ap.add_argument("--idle-exit", type=float, default=0, help="выйти после N секунд без новых событий при нулевом лаге")
    args = ap.parse_args()

    table = f"orders_by_customer_{args.version}"
    db = open_serving(args.db, table)
    delta = LOGIC[args.version]
    group = f"kappa_architecture_job_{args.version}"
    assigned: list[TopicPartition] = []

    def on_assign(consumer, partitions):
        assigned.extend(partitions)
        committed = consumer.committed(partitions, timeout=10)
        start = ", ".join(f"p{tp.partition}@{tp.offset if tp.offset >= 0 else 'нет, с начала лога'}" for tp in committed)
        print(f"[{args.version}] группа {group}, сохранённые offset'ы: {start}", flush=True)

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": group,
        "auto.offset.reset": "earliest",  # у новой группы offset'ов нет: читаем лог с нуля
        "enable.auto.commit": False,      # offset фиксируем сами, после записи в serving-таблицу
    })
    consumer.subscribe([TOPIC], on_assign=on_assign)

    t0 = time.monotonic()
    processed = 0
    caught_up_at = first_at = None
    processed_at_catch_up = 0
    last_report = last_msg = time.monotonic()
    while True:
        msgs = consumer.consume(num_messages=5000, timeout=0.5)
        now = time.monotonic()
        batch = defaultdict(lambda: [0, 0])
        for m in msgs:
            if m.error():
                raise KafkaException(m.error())
            ev = json.loads(m.value())
            acc = batch[ev["customer_id"]]
            acc[0] += delta(ev)
            acc[1] += 1
        if batch:
            # сначала результат в serving-таблицу, потом offset в Kafka: при сбое событие обработается
            # повторно (at-least-once), но не потеряется
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                f"INSERT INTO {table} VALUES (?, ?, ?) ON CONFLICT(customer_id) DO UPDATE SET "
                "revenue_cents = revenue_cents + excluded.revenue_cents, events = events + excluded.events",
                [(c, r, n) for c, (r, n) in batch.items()])
            db.execute("COMMIT")
            consumer.commit(asynchronous=False)
            processed += len(msgs)
            last_msg = now
            first_at = first_at or now
        if not assigned:
            continue
        if now - last_report >= 1.0 or (not msgs and caught_up_at is None):
            current_lag = lag(consumer)
            if now - last_report >= 1.0:
                print(f"[{args.version} +{now - t0:5.1f} с] обработано {processed:>7}, лаг {current_lag:>7}", flush=True)
                last_report = now
            if current_lag <= args.caught_up_lag and caught_up_at is None:
                caught_up_at = now
                processed_at_catch_up = processed
                print(f"[{args.version}] догнал голову лога за {now - t0:.1f} с (лаг {current_lag}), обработано {processed}", flush=True)
            if current_lag == 0 and args.exit_when_caught_up:
                break
        if args.idle_exit and caught_up_at and now - last_msg >= args.idle_exit and lag(consumer) == 0:
            print(f"[{args.version}] {args.idle_exit:.0f} с без новых событий, останавливаюсь", flush=True)
            break

    positions = consumer.committed(assigned, timeout=10)
    took = time.monotonic() - t0
    # скорость догоняния: от первого прочитанного события до нулевого лага, без ожидания вступления в группу
    rate = processed_at_catch_up / (caught_up_at - first_at) if caught_up_at and first_at and caught_up_at > first_at else 0
    speed = f", скорость догоняния {rate:.0f} событий/с" if rate else ""
    print(f"[{args.version}] итог: обработано {processed} за {took:.1f} с{speed}, offset'ы группы: "
          + ", ".join(f"p{tp.partition}@{tp.offset}" for tp in sorted(positions, key=lambda t: t.partition)), flush=True)
    consumer.close()
    db.close()


if __name__ == "__main__":
    main()
