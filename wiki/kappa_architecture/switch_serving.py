# confluent-kafka 2.16.1 (librdkafka 2.16.0), apache/kafka 4.3.2 KRaft, SQLite 3.45.1, прогнано на стенде 2026-11-14
"""Переключение приложения на таблицу новой версии джобы, шаги 3 и 4 пересчёта в Kappa.

Приложение читает только view orders_by_customer. Скрипт:
  1) проверяет, что джоба целевой версии догнала голову лога (лаг её consumer group = 0);
  2) сверяет каждую serving-таблицу с честным пересчётом, прочитанным напрямую из лога;
  3) показывает, сколько места занимают таблицы, пока живут обе версии;
  4) атомарно перенаправляет view на таблицу целевой версии;
  5) с --drop-old удаляет таблицу и consumer group старой версии.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict

from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.admin import AdminClient

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "127.0.0.1:59093")
TOPIC = "kappa_architecture_orders"
VIEW = "orders_by_customer"


def money(cents: int) -> str:
    return f"{cents / 100:,.2f}".replace(",", " ")


def log_bounds(consumer: Consumer) -> dict[int, tuple[int, int]]:
    meta = consumer.list_topics(TOPIC, timeout=10).topics[TOPIC]
    return {p: consumer.get_watermark_offsets(TopicPartition(TOPIC, p), timeout=10) for p in sorted(meta.partitions)}


def group_lag(consumer: Consumer, group: str, bounds: dict) -> int | None:
    # offset'ы чужой группы читаем отдельным consumer'ом с тем же group.id, не подписываясь на топик
    probe = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": group, "enable.auto.commit": False})
    committed = probe.committed([TopicPartition(TOPIC, p) for p in bounds], timeout=10)
    probe.close()
    if all(tp.offset < 0 for tp in committed):
        return None
    return sum(bounds[tp.partition][1] - max(tp.offset, bounds[tp.partition][0]) for tp in committed)


def recount_from_log(consumer: Consumer, bounds: dict) -> dict[str, int]:
    # честный пересчёт: читаем лог от начала до текущей головы, без consumer group и без commit
    consumer.assign([TopicPartition(TOPIC, p, low) for p, (low, _) in bounds.items()])
    left = {p: high - low for p, (low, high) in bounds.items() if high > low}
    truth: dict[str, int] = defaultdict(int)
    while left:
        for m in consumer.consume(num_messages=5000, timeout=1.0):
            if m.partition() not in left or m.offset() >= bounds[m.partition()][1]:
                continue
            ev = json.loads(m.value())
            sign = 1 if ev["type"] == "order" else -1
            truth[ev["customer_id"]] += sign * ev["amount_cents"]
            left[m.partition()] -= 1
            if left[m.partition()] == 0:
                del left[m.partition()]
    consumer.unassign()
    return truth


def table_sizes(db: sqlite3.Connection) -> dict[str, int]:
    # dbstat считает страницы самой таблицы и её индекса первичного ключа
    rows = db.execute("SELECT m.tbl_name, SUM(d.pgsize) FROM dbstat d JOIN sqlite_master m ON m.name = d.name "
                      "WHERE m.tbl_name LIKE 'orders_by_customer_v%' GROUP BY m.tbl_name ORDER BY 1").fetchall()
    return dict(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", choices=["v1", "v2"], required=True)
    ap.add_argument("--db", default="serving.db")
    ap.add_argument("--drop-old", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, isolation_level=None)
    reader = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "kappa_architecture_switch_probe",
                       "enable.auto.commit": False})
    bounds = log_bounds(reader)
    print(f"лог {TOPIC}:", ", ".join(f"p{p} offset'ы {lo}..{hi - 1}" for p, (lo, hi) in bounds.items()),
          f"| всего событий {sum(hi - lo for lo, hi in bounds.values())}")

    # 1) целевая версия обязана догнать голову лога, иначе приложение увидит неполные данные
    target_lag = group_lag(reader, f"kappa_architecture_job_{args.to}", bounds)
    print(f"лаг джобы {args.to}: {target_lag}")
    if target_lag != 0:
        print(f"ОТКАЗ: джоба {args.to} не догнала лог, переключать рано")
        sys.exit(2)

    # 2) сверка serving-таблиц с честным пересчётом
    truth = recount_from_log(reader, bounds)
    reader.close()
    tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                        "AND name LIKE 'orders_by_customer_v%' ORDER BY name")]
    sample = None
    for t in tables:
        got = dict(db.execute(f"SELECT customer_id, revenue_cents FROM {t}"))
        wrong = [c for c in truth if got.get(c) != truth[c]]
        sample = sample or (wrong[0] if wrong else None)
        print(f"{t}: клиентов {len(got)}, выручка {money(sum(got.values()))}, "
              f"расходится с пересчётом из лога у {len(wrong)} клиентов")
    print(f"пересчёт из лога: клиентов {len(truth)}, выручка {money(sum(truth.values()))}")
    if sample:
        row = {t: db.execute(f"SELECT revenue_cents FROM {t} WHERE customer_id = ?", (sample,)).fetchone()[0]
               for t in tables}
        print(f"пример, клиент {sample}: " + ", ".join(f"{t} = {money(v)}" for t, v in row.items())
              + f", пересчёт = {money(truth[sample])}")

    # 3) место: пока не удалена старая таблица, serving-хранилище держит обе версии
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sizes = table_sizes(db)
    print("место в serving-БД:", ", ".join(f"{t} {s / 1024:.0f} КиБ" for t, s in sizes.items()),
          f"| файл {os.path.getsize(args.db) / 1024:.0f} КиБ")

    # 4) переключение одной транзакцией: читатель видит либо старую таблицу, либо новую
    before = db.execute(f"SELECT sql FROM sqlite_master WHERE name = '{VIEW}'").fetchone()
    db.execute("BEGIN IMMEDIATE")
    db.execute(f"DROP VIEW IF EXISTS {VIEW}")
    db.execute(f"CREATE VIEW {VIEW} AS SELECT * FROM orders_by_customer_{args.to}")
    db.execute("COMMIT")
    print(f"view {VIEW}: было «{before[0] if before else 'нет'}», стало → orders_by_customer_{args.to}")
    if sample:
        val = db.execute(f"SELECT revenue_cents FROM {VIEW} WHERE customer_id = ?", (sample,)).fetchone()[0]
        print(f"приложение читает {VIEW}, клиент {sample}: {money(val)}")

    # 5) шаг 4 по Kreps: старая джоба остановлена, её таблица и consumer group больше не нужны
    if args.drop_old:
        old = "v1" if args.to == "v2" else "v2"
        db.execute(f"DROP TABLE IF EXISTS orders_by_customer_{old}")
        db.execute("VACUUM")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # в режиме WAL файл БД сжимается только на checkpoint
        admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
        for g, fut in admin.delete_consumer_groups([f"kappa_architecture_job_{old}"], request_timeout=10).items():
            fut.result()
            print(f"удалены таблица orders_by_customer_{old} и consumer group {g}")
        print("место после удаления:", ", ".join(f"{t} {s / 1024:.0f} КиБ" for t, s in table_sizes(db).items()),
              f"| файл {os.path.getsize(args.db) / 1024:.0f} КиБ")
    db.close()


if __name__ == "__main__":
    main()
