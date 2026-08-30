# confluent-kafka 2.15.0, DuckDB 1.5.5, Apache Kafka 4.3.0 в KRaft на стенде event_streaming,
# прогнано на стенде 2026-08-30
"""Читает поток заказов, сразу пишет каждое событие в DuckDB и пересчитывает агрегат по
категориям. Печатает задержку между моментом события и моментом, когда обновлённый агрегат
стал доступен запросу — это и есть задержка «событие -> инсайт» в real-time аналитике.
Запускать первым: скрипт ждёт назначения партиций, прежде чем producer.py начнёт слать события."""
import json
import os
import time

import duckdb
from confluent_kafka import Consumer
from confluent_kafka.admin import AdminClient, NewTopic

BROKER = "localhost:9092"
TOPIC = "real_time_analytics_events"
DB_PATH = os.path.join(os.path.dirname(__file__), "realtime_analytics.duckdb")
EVENT_COUNT = 30
POLL_TIMEOUT = 1.0
IDLE_LIMIT = 5  # столько пустых опросов подряд после назначения партиций считаем концом потока


def create_topic() -> None:
    """Топик создаётся здесь, а не в producer.py: если подписаться до его создания,
    первый опрос падает на UNKNOWN_TOPIC_OR_PART и часть событий уходит в догоняющую
    пачку вместо равномерного потока — задержка первых событий тогда врёт."""
    admin = AdminClient({"bootstrap.servers": BROKER})
    existing = admin.list_topics(timeout=10).topics
    if TOPIC in existing:
        print(f"топик {TOPIC} уже есть")
        return
    admin.create_topics([NewTopic(TOPIC, num_partitions=1, replication_factor=1)])[TOPIC].result()
    print(f"топик {TOPIC} создан")


def main() -> None:
    create_topic()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # чистый прогон, старые события не искажают агрегат
    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE events (
            event_id INTEGER,
            event_time DOUBLE,
            category VARCHAR,
            amount DOUBLE
        )
    """)

    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": "realtime_analytics_dashboard",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    state = {"assigned": False}

    def on_assign(_consumer, partitions):
        state["assigned"] = True
        print(f"группа получила партиции {sorted(p.partition for p in partitions)}, жду события", flush=True)

    consumer.subscribe([TOPIC], on_assign=on_assign)

    latencies = []
    idle = 0
    while len(latencies) < EVENT_COUNT and idle < IDLE_LIMIT:
        msg = consumer.poll(POLL_TIMEOUT)
        if msg is None:
            if state["assigned"]:  # пустой опрос до назначения партиций концом потока не считается
                idle += 1
            continue
        if msg.error():
            print(f"ОШИБКА: {msg.error()}")
            continue
        idle = 0
        payload = json.loads(msg.value())

        # вставка и пересчёт агрегата — это и есть путь «запрос увидел новые данные»
        con.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            [payload["event_id"], payload["event_time"], payload["category"], payload["amount"]],
        )
        con.execute("SELECT category, SUM(amount), COUNT(*) FROM events GROUP BY category").fetchall()
        t_ready = time.time()

        latency = t_ready - payload["event_time"]
        latencies.append(latency)
        print(f"событие {payload['event_id']:>2} ({payload['category']}): задержка {latency:.3f} с", flush=True)

    consumer.close()

    print(f"\nобработано событий: {len(latencies)}")
    if latencies:
        print(f"задержка событие -> доступный агрегат: мин {min(latencies):.3f} с, "
              f"среднее {sum(latencies) / len(latencies):.3f} с, макс {max(latencies):.3f} с")

    print("\nитоговый агрегат по категориям:")
    for category, total, count in con.execute(
        "SELECT category, SUM(amount), COUNT(*) FROM events GROUP BY category ORDER BY category"
    ).fetchall():
        print(f"  {category:<12} сумма {total:>9.2f}  заказов {count}")

    con.close()


if __name__ == "__main__":
    main()
