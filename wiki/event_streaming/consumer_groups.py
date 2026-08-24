# confluent-kafka 2.15.0, Apache Kafka 4.3.0 в KRaft, прогнано на стенде 2026-08-24
"""Чтение одного лога разными группами: независимость групп, оффсеты, повторное чтение."""
import json
import time
from confluent_kafka import Consumer, TopicPartition, KafkaError

BROKER = "localhost:9092"
TOPIC = "orders"
PARTITIONS = 3
POLL_TIMEOUT = 1.0
IDLE_LIMIT = 5  # столько пустых опросов подряд после назначения партиций считаем концом лога


def base_config(group_id: str) -> dict:
    return {
        "bootstrap.servers": BROKER,
        "group.id": group_id,
        "auto.offset.reset": "earliest",  # новая группа начинает с начала лога, а не с конца
        "enable.auto.commit": False,      # оффсеты фиксируем руками, чтобы видеть момент коммита
    }


def subscribe(consumer: Consumer, group_id: str) -> dict:
    """Подписка с колбэком назначения: пока партиции не розданы, читать нечего."""
    state = {"assigned": False}

    def on_assign(_consumer, partitions):
        state["assigned"] = True
        print(f"[{group_id}] группа получила партиции {sorted(p.partition for p in partitions)}")

    consumer.subscribe([TOPIC], on_assign=on_assign)
    return state


def drain(consumer: Consumer, label: str, state: dict, timeout: float = 60.0) -> int:
    """Читает топик до конца лога и печатает, что вычитал."""
    seen, idle = [], 0
    deadline = time.time() + timeout
    while idle < IDLE_LIMIT and time.time() < deadline:
        msg = consumer.poll(POLL_TIMEOUT)
        if msg is None:
            if state["assigned"]:  # пустой опрос до назначения партиций концом лога не считается
                idle += 1
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                print(f"[{label}] ОШИБКА: {msg.error()}")
            continue
        idle = 0
        payload = json.loads(msg.value())
        seen.append((msg.partition(), msg.offset(), payload["order"]))
    print(f"[{label}] прочитано событий: {len(seen)}")
    for partition, offset, order in seen:
        print(f"[{label}]   партиция {partition} оффсет {offset} заказ {order}")
    return len(seen)


def show_committed(consumer: Consumer, group_id: str) -> None:
    """Позиция группы в логе хранится на брокере и переживает остановку потребителя."""
    parts = [TopicPartition(TOPIC, p) for p in range(PARTITIONS)]
    for tp in consumer.committed(parts, timeout=10):
        value = "нет" if tp.offset < 0 else tp.offset
        print(f"[{group_id}] зафиксированный оффсет партиции {tp.partition}: {value}")


def read_as(group_id: str, commit: bool = True) -> int:
    consumer = Consumer(base_config(group_id))
    state = subscribe(consumer, group_id)
    count = drain(consumer, group_id, state)
    if commit and count:
        consumer.commit(asynchronous=False)  # фиксируем позицию явно
    show_committed(consumer, group_id)
    consumer.close()
    return count


def two_consumers_one_group(group_id: str) -> None:
    """Внутри группы партиции делятся между потребителями, каждая достаётся ровно одному."""
    consumers = [Consumer(base_config(group_id)) for _ in range(2)]
    for consumer in consumers:
        consumer.subscribe([TOPIC])
    deadline = time.time() + 30
    while time.time() < deadline:
        held = []
        for consumer in consumers:
            consumer.poll(0.5)
            held.append(sorted(tp.partition for tp in consumer.assignment()))
        if all(held) and sum(len(h) for h in held) == PARTITIONS:
            break
    for i, consumer in enumerate(consumers, start=1):
        parts = sorted(tp.partition for tp in consumer.assignment())
        print(f"[{group_id}] потребитель {i} держит партиции {parts}")
    for consumer in consumers:
        consumer.close()


def main() -> None:
    print("=== группа analytics читает лог с начала ===")
    first = read_as("analytics")

    print("=== группа billing читает тот же лог независимо ===")
    second = read_as("billing")
    print(f"обе группы вычитали одинаковое число событий: {first == second} ({first})")

    print("=== analytics подключается снова: продолжает с зафиксированного оффсета ===")
    again = read_as("analytics")
    print(f"новых событий для analytics: {again}")

    print("=== повторное чтение истории новой группой audit_replay ===")
    replay = read_as("audit_replay", commit=False)
    print(f"replay поднял из лога событий: {replay}")

    print("=== два потребителя в одной группе делят партиции ===")
    two_consumers_one_group("delivery")


if __name__ == "__main__":
    main()
