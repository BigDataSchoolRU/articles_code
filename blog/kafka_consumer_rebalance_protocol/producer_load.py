# confluent-kafka 2.16.0, Apache Kafka 4.3.2, прогнано на стенде 2026-10-22
"""Ровная нагрузка в топик: по RATE сообщений в секунду в каждую партицию.

Задержку чтения потребитель считает по CreateTime сообщения, поэтому продюсер
пишет в каждую партицию равномерно и без пауз. Запуск отдельно:
    python producer_load.py            # пишет, пока не нажать Ctrl+C
"""

import os
import sys
import time

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP = os.environ.get("BOOTSTRAP", "localhost:9092,localhost:9094,localhost:9096")
TOPIC = "rebalance-bench"
PARTITIONS = 12
RATE = 100  # сообщений в секунду на партицию, всего 1200/с


def ensure_topic() -> None:
    """Создаёт топик на 12 партиций с RF=3, если его ещё нет."""
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    if TOPIC in admin.list_topics(timeout=10).topics:
        return
    fut = admin.create_topics([NewTopic(TOPIC, PARTITIONS, 3)])[TOPIC]
    fut.result()


def run(stop=None) -> None:
    """Пишет пачку «по одному сообщению в каждую партицию» каждые 1/RATE секунды."""
    ensure_topic()
    producer = Producer({"bootstrap.servers": BOOTSTRAP, "linger.ms": 5, "acks": 1})
    step = 1.0 / RATE
    next_t = time.time()
    sent = 0
    while stop is None or not stop.is_set():
        for p in range(PARTITIONS):
            producer.produce(TOPIC, value=b"x" * 100, partition=p)
        sent += PARTITIONS
        producer.poll(0)
        next_t += step
        delay = next_t - time.time()
        if delay > 0:
            time.sleep(delay)
    producer.flush(10)
    print(f"продюсер остановлен, отправлено {sent}", flush=True)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
