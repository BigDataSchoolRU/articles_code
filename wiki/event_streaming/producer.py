# confluent-kafka 2.15.0, Apache Kafka 4.3.0 в KRaft, прогнано на стенде 2026-08-24
"""Запись событий в топик: лог из трёх партиций, ключ определяет партицию."""
import json
import time
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

BROKER = "localhost:9092"
TOPIC = "orders"
PARTITIONS = 3

# события четырёх магазинов, ключ это идентификатор магазина
EVENTS = [
    {"store": "msk-01", "order": 1001, "amount": 2500},
    {"store": "omsk-08", "order": 1002, "amount": 700},
    {"store": "msk-01", "order": 1003, "amount": 1900},
    {"store": "ekb-03", "order": 1004, "amount": 4300},
    {"store": "omsk-08", "order": 1005, "amount": 150},
    {"store": "kzn-05", "order": 1006, "amount": 8800},
    {"store": "msk-01", "order": 1007, "amount": 320},
    {"store": "ekb-03", "order": 1008, "amount": 1150},
]


def create_topic() -> None:
    """Топик создаётся явно: автосоздание на стенде выключено."""
    admin = AdminClient({"bootstrap.servers": BROKER})
    existing = admin.list_topics(timeout=10).topics
    if TOPIC in existing:
        print(f"топик {TOPIC} уже есть, партиций: {len(existing[TOPIC].partitions)}")
        return
    new_topic = NewTopic(TOPIC, num_partitions=PARTITIONS, replication_factor=1)
    for name, fut in admin.create_topics([new_topic]).items():
        fut.result()  # бросит исключение, если создать не удалось
        print(f"топик {name} создан, партиций: {PARTITIONS}")


def main() -> None:
    create_topic()
    # acks=all: продюсер ждёт подтверждения от всех синхронных реплик
    producer = Producer({"bootstrap.servers": BROKER, "acks": "all"})
    placed = []

    def on_delivery(err, msg):
        """Колбэк подтверждения: сюда приходит партиция и оффсет записи в логе."""
        if err is not None:
            print(f"ОШИБКА доставки: {err}")
            return
        placed.append((msg.key().decode(), msg.partition(), msg.offset()))

    t0 = time.time()
    for event in EVENTS:
        producer.produce(
            TOPIC,
            key=event["store"].encode(),
            value=json.dumps(event).encode(),
            on_delivery=on_delivery,
        )
    producer.flush(15)  # дожидаемся всех подтверждений
    elapsed = time.time() - t0

    print(f"записано событий: {len(placed)} за {elapsed:.3f} с")
    print("ключ -> партиция:оффсет")
    for key, partition, offset in placed:
        print(f"  {key} -> {partition}:{offset}")

    # события одного магазина обязаны лежать в одной партиции: порядок гарантируется в её пределах
    by_key = {}
    for key, partition, _ in placed:
        by_key.setdefault(key, set()).add(partition)
    for key, parts in sorted(by_key.items()):
        print(f"  ключ {key}: партиции {sorted(parts)}")


if __name__ == "__main__":
    main()
