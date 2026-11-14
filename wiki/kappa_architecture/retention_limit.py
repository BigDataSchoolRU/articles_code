# confluent-kafka 2.16.1 (librdkafka 2.16.0), apache/kafka 4.3.2 KRaft, прогнано на стенде 2026-11-14
"""Ограничение Kappa: пересчитать можно только то, что ещё лежит в логе.

Топик с коротким retention (10 с). Пишем старую пачку событий, через 6 с новую (она открывает новый
сегмент), ждём, пока брокер удалит сегмент со старой пачкой, снимаем ограничение retention, чтобы
новая пачка уцелела, и перепроигрываем лог с начала.
Kafka не сообщает об ошибке: consumer с auto.offset.reset=earliest молча начинает с нового начала лога.
"""
import json
import os
import random
import time

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, AlterConfigOpType, ConfigEntry, ConfigResource, NewTopic

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "127.0.0.1:59093")
TOPIC = "kappa_architecture_orders_short_retention"
BATCH = 3000


def write_batch(producer: Producer, rng: random.Random, first_id: int) -> int:
    revenue = 0
    for i in range(BATCH):
        kind = "refund" if rng.random() < 0.10 else "order"
        amount = rng.randint(500, 50_000)
        revenue += amount if kind == "order" else -amount
        ev = {"event_id": first_id + i, "customer_id": f"c{rng.randint(1, 500):05d}", "type": kind,
              "amount_cents": amount, "ts_ms": int(time.time() * 1000)}
        producer.produce(TOPIC, value=json.dumps(ev))
    producer.flush(30)
    return revenue


def main() -> None:
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    # retention.ms=10000: сегмент удаляется, когда его самое свежее событие старше 10 с;
    # segment.ms=2000: запись спустя 2 с открывает новый сегмент, старый становится кандидатом на удаление
    config = {"retention.ms": "10000", "segment.ms": "2000"}
    # каждый запуск начинает с пустого топика: прошлый запуск оставил его с retention.ms=-1
    if TOPIC in admin.list_topics(timeout=10).topics:
        admin.delete_topics([TOPIC])[TOPIC].result()
    for _ in range(30):
        try:
            admin.create_topics([NewTopic(TOPIC, num_partitions=1, replication_factor=1, config=config)])[TOPIC].result()
            break
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
            time.sleep(1)  # удаление топика асинхронное, ждём, пока брокер его доудалит
    print(f"топик {TOPIC}: 1 партиция, {config}")

    rng = random.Random(7)
    producer = Producer({"bootstrap.servers": BOOTSTRAP, "enable.idempotence": True})
    tp = TopicPartition(TOPIC, 0)
    t0 = time.monotonic()
    old = write_batch(producer, rng, 1)
    time.sleep(6)
    new = write_batch(producer, rng, BATCH + 1)
    truth = old + new
    probe = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "kappa_architecture_retention_probe"})
    low, high = probe.get_watermark_offsets(tp, timeout=10)
    print(f"записано 2 пачки по {BATCH}: лог offset'ы {low}..{high - 1}, честная выручка {truth / 100:.2f}")

    # ждём, пока проверка retention (раз в 5 с на этом стенде) удалит старый сегмент
    while low == 0 and time.monotonic() - t0 < 90:
        time.sleep(1)
        low, high = probe.get_watermark_offsets(tp, timeout=10, cached=False)
    print(f"через {time.monotonic() - t0:.0f} с: начало лога сдвинулось на offset {low}, "
          f"в логе осталось {high - low} событий из {2 * BATCH}")

    # поднимаем retention до бессрочного: новая пачка уцелеет, а удалённую старую это не вернёт
    res = ConfigResource(ConfigResource.Type.TOPIC, TOPIC, incremental_configs=[
        ConfigEntry("retention.ms", "-1", incremental_operation=AlterConfigOpType.SET)])
    admin.incremental_alter_configs([res])[res].result()
    low, high = probe.get_watermark_offsets(tp, timeout=10, cached=False)
    probe.close()
    print(f"retention.ms=-1 выставлен: лог offset'ы {low}..{high - 1}, удалённое не вернулось")

    # пересчёт «с нуля» новой группой: никакой ошибки, просто меньше событий
    replay = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "kappa_architecture_replay",
                       "auto.offset.reset": "earliest", "enable.auto.commit": False})
    # отдельная группа без сохранённых offset'ов: так стартует новая версия джобы в Kappa
    replay.subscribe([TOPIC])
    seen, revenue, first = 0, 0, None
    deadline = time.monotonic() + 30
    while seen < high - low and time.monotonic() < deadline:
        for m in replay.consume(num_messages=1000, timeout=1.0):
            if m.error():
                raise KafkaException(m.error())
            first = m.offset() if first is None else first
            ev = json.loads(m.value())
            revenue += ev["amount_cents"] if ev["type"] == "order" else -ev["amount_cents"]
            seen += 1
    replay.close()
    print(f"пересчёт с earliest: первый offset {first}, прочитано {seen} событий, выручка {revenue / 100:.2f}")
    print(f"потеряно при пересчёте: {2 * BATCH - seen} событий, {(truth - revenue) / 100:.2f} выручки; "
          "ошибок от Kafka: 0")


if __name__ == "__main__":
    main()
