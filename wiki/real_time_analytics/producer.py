# confluent-kafka 2.15.0, Apache Kafka 4.3.0 в KRaft, брокер переиспользован со стенда
# event_streaming, прогнано на стенде 2026-08-30
"""Симулирует непрерывный поток заказов: события идут по одному с паузами, а не пачкой разом.
Запускать вторым: топик создаёт consumer_realtime.py, он же должен подтвердить назначение
партиций в своём выводе («жду события»), прежде чем стартует этот скрипт — иначе первые
события уйдут в топик до появления потребителя и задержка получится не той, что в реальном
потоке."""
import json
import random
import time

from confluent_kafka import Producer

BROKER = "localhost:9092"
TOPIC = "real_time_analytics_events"
EVENT_COUNT = 30
CATEGORIES = ["electronics", "clothing", "grocery", "books"]

random.seed(42)


def main() -> None:
    producer = Producer({"bootstrap.servers": BROKER, "acks": "all"})
    sent = 0

    def on_delivery(err, msg):
        nonlocal sent
        if err is not None:
            print(f"ОШИБКА доставки: {err}")
            return
        sent += 1

    t0 = time.time()
    for i in range(1, EVENT_COUNT + 1):
        event = {
            "event_id": i,
            "event_time": time.time(),  # момент, когда покупка реально произошла
            "category": random.choice(CATEGORIES),
            "amount": round(random.uniform(10, 500), 2),
        }
        producer.produce(TOPIC, value=json.dumps(event).encode(), on_delivery=on_delivery)
        producer.poll(0)  # даёт колбэкам доставки отработать, не дожидаясь их
        time.sleep(random.uniform(0.05, 0.3))  # неравномерный поток вместо пачки
    producer.flush(15)
    elapsed = time.time() - t0

    print(f"отправлено событий: {sent} из {EVENT_COUNT} за {elapsed:.2f} с")


if __name__ == "__main__":
    main()
