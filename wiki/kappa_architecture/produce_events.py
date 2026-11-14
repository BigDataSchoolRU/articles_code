# confluent-kafka 2.16.1 (librdkafka 2.16.0), apache/kafka 4.3.2 KRaft, прогнано на стенде 2026-11-14
"""Пишет события заказов в неизменяемый лог Kafka.

Два режима: история одной пачкой (--rate 0) и живой поток с заданным темпом (--rate N событий в секунду).
Генератор детерминирован по --seed, поэтому прогон воспроизводится.
"""
import argparse
import json
import os
import random
import time

from confluent_kafka import KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "127.0.0.1:59093")
TOPIC = "kappa_architecture_orders"
PARTITIONS = 3
CUSTOMERS = 5000


def ensure_topic(admin: AdminClient) -> None:
    # retention.ms=-1: лог хранится бессрочно, иначе пересчёт истории с нуля невозможен
    config = {"retention.ms": "-1", "retention.bytes": "-1"}
    futures = admin.create_topics([NewTopic(TOPIC, num_partitions=PARTITIONS, replication_factor=1, config=config)])
    for name, fut in futures.items():
        try:
            fut.result()
            print(f"топик {name} создан: {PARTITIONS} партиции, {config}")
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
            print(f"топик {name} уже есть")


def make_event(rng: random.Random, event_id: int) -> dict:
    # 10% событий это возвраты: сумма в них положительная, тип говорит, что её надо вычесть
    return {
        "event_id": event_id,
        "customer_id": f"c{rng.randint(1, CUSTOMERS):05d}",
        "type": "refund" if rng.random() < 0.10 else "order",
        "amount_cents": rng.randint(500, 50_000),
        "ts_ms": int(time.time() * 1000),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--first-id", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rate", type=int, default=0, help="событий в секунду, 0 = без ограничения")
    args = ap.parse_args()

    ensure_topic(AdminClient({"bootstrap.servers": BOOTSTRAP}))
    producer = Producer({"bootstrap.servers": BOOTSTRAP, "enable.idempotence": True, "linger.ms": 20})
    rng = random.Random(args.seed)
    refunds = 0
    t0 = time.monotonic()
    for i in range(args.count):
        ev = make_event(rng, args.first_id + i)
        refunds += ev["type"] == "refund"
        # ключ = клиент: все события клиента попадают в одну партицию и читаются по порядку
        while True:
            try:
                producer.produce(TOPIC, key=ev["customer_id"], value=json.dumps(ev))
                break
            except BufferError:
                producer.poll(0.1)  # локальная очередь librdkafka полна: ждём подтверждений брокера
        producer.poll(0)
        if args.rate and (i + 1) % max(1, args.rate // 10) == 0:
            # держим темп живого потока: десять порций в секунду
            ahead = (i + 1) / args.rate - (time.monotonic() - t0)
            if ahead > 0:
                time.sleep(ahead)
    producer.flush(30)
    took = time.monotonic() - t0
    print(f"записано {args.count} событий (id {args.first_id}..{args.first_id + args.count - 1}), "
          f"из них возвратов {refunds}, за {took:.1f} с, {args.count / took:.0f} событий/с")


if __name__ == "__main__":
    main()
