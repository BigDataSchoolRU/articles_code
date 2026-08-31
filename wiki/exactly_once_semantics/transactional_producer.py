# confluent-kafka 2.15.0, Apache Kafka 4.3.0 в KRaft (стенд event_streaming), прогнано на стенде 2026-08-31
"""Транзакционный producer: атомарная запись в несколько партиций, consumer с read_committed
не видит записи из отменённой транзакции — то, что в логе видно, зависит от isolation.level."""
from confluent_kafka import Consumer, Producer, TopicPartition

BROKER = "localhost:9092"
TOPIC = "exactly_once_semantics_events"
COMMITTED_PARTITIONS = (1, 2)  # одна транзакция атомарно пишет в обе партиции
ABORTED_PARTITION = 1


def run_transactions() -> None:
    producer = Producer({
        "bootstrap.servers": BROKER,
        "transactional.id": "exactly-once-demo-txn",
        "enable.idempotence": True,  # транзакции в Kafka построены поверх идемпотентного producer
    })
    producer.init_transactions()  # регистрирует producer в координаторе транзакций, получает PID

    # транзакция 1: атомарная запись в две партиции, фиксируется
    producer.begin_transaction()
    for partition in COMMITTED_PARTITIONS:
        producer.produce(TOPIC, key=b"committed", value=f"committed-p{partition}".encode(), partition=partition)
    producer.flush()
    producer.commit_transaction()
    print(f"транзакция 1 закоммичена: записи в партициях {COMMITTED_PARTITIONS}")

    # транзакция 2: имитация сбоя обработки после записи — откатываем
    producer.begin_transaction()
    producer.produce(TOPIC, key=b"aborted", value=b"aborted-message", partition=ABORTED_PARTITION)
    producer.flush()
    producer.abort_transaction()
    print(f"транзакция 2 отменена: запись в партиции {ABORTED_PARTITION} помечена aborted")


def read_partitions(isolation_level: str) -> list[tuple[int, bytes, bytes]]:
    """Партиции читаются с нуля отдельной группой на каждый isolation.level, чтобы прогоны не влияли друг на друга."""
    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": f"txn-demo-check-{isolation_level}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "isolation.level": isolation_level,
    })
    consumer.assign([TopicPartition(TOPIC, p, 0) for p in set(COMMITTED_PARTITIONS + (ABORTED_PARTITION,))])
    seen, idle = [], 0
    while idle < 5:
        msg = consumer.poll(1.0)
        if msg is None:
            idle += 1
            continue
        idle = 0
        if msg.error():
            continue
        seen.append((msg.partition(), msg.key(), msg.value()))
    consumer.close()
    return seen


def main() -> None:
    run_transactions()

    for level in ("read_committed", "read_uncommitted"):
        records = read_partitions(level)
        keys = sorted(k.decode() for _, k, _ in records)
        print(f"\nisolation.level={level}: прочитано записей {len(records)}, ключи {keys}")
        has_aborted = any(k == b"aborted" for _, k, _ in records)
        print(f"  запись из отменённой транзакции видна: {has_aborted}")


if __name__ == "__main__":
    main()
