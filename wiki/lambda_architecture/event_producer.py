# confluent-kafka 2.15.0, Apache Kafka 4.3.0 KRaft, прогнано на стенде 2026-09-05
"""Единая точка входа событий Lambda Architecture: каждое событие уходит сразу в Kafka
(источник speed layer) и дописывается в append-only мастер-датасет (источник batch layer).
Это и есть точка ветвления архитектуры на два параллельных пути."""
import json
import sys
from pathlib import Path

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

BROKER = "localhost:9092"
TOPIC = "lambda_architecture_events"
MASTER_FILE = Path(__file__).parent / "master_dataset.jsonl"

# BATCH_1 — трафик, который «уже случился» до прогона batch layer.
# BATCH_2 — события, пришедшие уже после того, как batch layer пересчитал представление:
# их видит только speed layer, пока не отработает следующий batch-прогон.
BATCHES = {
    1: [
        {"page": "/home", "views": 5, "ts": 1000},
        {"page": "/docs", "views": 3, "ts": 1001},
        {"page": "/pricing", "views": 2, "ts": 1002},
        {"page": "/home", "views": 4, "ts": 1003},
        {"page": "/blog", "views": 1, "ts": 1004},
        {"page": "/docs", "views": 6, "ts": 1005},
        {"page": "/home", "views": 3, "ts": 1006},
        {"page": "/pricing", "views": 5, "ts": 1007},
        {"page": "/blog", "views": 2, "ts": 1008},
        {"page": "/docs", "views": 2, "ts": 1009},
    ],
    2: [
        {"page": "/home", "views": 7, "ts": 1010},
        {"page": "/pricing", "views": 3, "ts": 1011},
        {"page": "/home", "views": 2, "ts": 1012},
    ],
}


def ensure_topic() -> None:
    """Топик создаётся явно один раз: автосоздание на стенде выключено."""
    admin = AdminClient({"bootstrap.servers": BROKER})
    existing = admin.list_topics(timeout=10).topics
    if TOPIC in existing:
        return
    new_topic = NewTopic(TOPIC, num_partitions=1, replication_factor=1)
    for name, fut in admin.create_topics([new_topic]).items():
        fut.result()  # бросит исключение, если создать не удалось
        print(f"топик {name} создан")


def append_to_master(events: list[dict]) -> None:
    """Append-only мастер-датасет: старые строки никогда не переписываются и не удаляются,
    только дописываются новые. В batch layer это и есть источник истины."""
    with MASTER_FILE.open("a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def produce_to_kafka(events: list[dict]) -> None:
    producer = Producer({"bootstrap.servers": BROKER, "acks": "all"})
    delivered = []

    def on_delivery(err, msg):
        if err is not None:
            print(f"ОШИБКА доставки: {err}")
            return
        delivered.append(msg.offset())

    for event in events:
        producer.produce(
            TOPIC,
            value=json.dumps(event, ensure_ascii=False).encode(),
            on_delivery=on_delivery,
        )
    producer.flush(15)
    print(f"в Kafka записано событий: {len(delivered)}, оффсеты {delivered[0]}-{delivered[-1]}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("1", "2"):
        raise SystemExit("использование: event_producer.py <1|2>")
    batch_no = int(sys.argv[1])
    events = BATCHES[batch_no]

    print(f"=== пакет {batch_no}: {len(events)} событий, ts {events[0]['ts']}-{events[-1]['ts']} ===")
    ensure_topic()
    produce_to_kafka(events)
    append_to_master(events)
    print(f"мастер-датасет дополнен: {MASTER_FILE.name}")


if __name__ == "__main__":
    main()
