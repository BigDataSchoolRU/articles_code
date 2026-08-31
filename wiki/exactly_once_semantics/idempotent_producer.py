# confluent-kafka 2.15.0, Apache Kafka 4.3.0 в KRaft (стенд exactly_once_semantics_kafka), прогнано на стенде 2026-08-31
"""Идемпотентный producer: реальный ретрай на уровне протокола не создаёт дубль в логе."""
import subprocess
import threading
import time
from confluent_kafka import Consumer, Producer, TopicPartition

BROKER = "localhost:9092"
TOPIC = "exactly_once_semantics_events"
PARTITION = 0
CONTAINER = "exactly_once_semantics_kafka"
KEY = b"order-idempotent-demo"
FREEZE_SECONDS = 6.0  # дольше request.timeout.ms ниже, чтобы вызвать настоящий таймаут запроса


def freeze_broker() -> None:
    """`docker pause` останавливает процессы в контейнере: брокер не отвечает, но TCP-сессия жива —
    клиент не видит разрыв соединения, а именно таймаут ответа на конкретный запрос."""
    subprocess.run(["docker", "pause", CONTAINER], check=True)


def unpause_after(seconds: float) -> None:
    time.sleep(seconds)
    subprocess.run(["docker", "unpause", CONTAINER], check=True)


def produce_through_freeze() -> tuple[int, float]:
    freeze_broker()
    unfreeze = threading.Thread(target=unpause_after, args=(FREEZE_SECONDS,))
    unfreeze.start()

    producer = Producer({
        "bootstrap.servers": BROKER,
        "enable.idempotence": True,  # PID продюсера + порядковый номер на партицию защищают от дублей при ретрае
        "acks": "all",
        "message.timeout.ms": 25000,  # общий бюджет доставки, должен пережить заморозку
        "request.timeout.ms": 2000,   # короче заморозки: запрос гарантированно уйдёт в ретрай
        "retry.backoff.ms": 500,
    })

    delivered = []

    def on_delivery(err, msg):
        if err is not None:
            print(f"ОШИБКА доставки: {err}")
            return
        delivered.append((msg.partition(), msg.offset()))

    t0 = time.time()
    producer.produce(TOPIC, key=KEY, value=b"payload", partition=PARTITION, on_delivery=on_delivery)
    producer.flush(25)  # блокируется, пока брокер заморожен, и отпускает ретраи после разморозки
    elapsed = time.time() - t0

    unfreeze.join()
    if not delivered:
        raise RuntimeError("сообщение не доставлено — проверьте, поднят ли брокер")
    return delivered[0][1], elapsed


def count_records_with_key() -> int:
    """Читает партицию с начала и считает записи с нашим ключом — с идемпотентностью должна быть ровно одна."""
    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": "idempotent-demo-check",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.assign([TopicPartition(TOPIC, PARTITION, 0)])
    count, idle = 0, 0
    while idle < 5:
        msg = consumer.poll(1.0)
        if msg is None:
            idle += 1
            continue
        idle = 0
        if msg.error():
            continue
        if msg.key() == KEY:
            count += 1
    consumer.close()
    return count


def main() -> None:
    print(f"замораживаем брокер на {FREEZE_SECONDS:.0f} с и отправляем сообщение с idempotence=True")
    offset, elapsed = produce_through_freeze()
    print(f"доставлено на оффсет {offset} за {elapsed:.2f} с "
          f"(время близко к {FREEZE_SECONDS:.0f} с — доставка ждала ретраев, пока брокер был заморожен)")

    count = count_records_with_key()
    print(f"записей с ключом {KEY.decode()!r} в логе: {count}")
    print("дублей нет — ретраи под капотом идемпотентны" if count == 1
          else f"ВНИМАНИЕ: обнаружены дубли ({count})")


if __name__ == "__main__":
    main()
