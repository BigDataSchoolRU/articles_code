# confluent-kafka 2.16.0, Apache Kafka 4.3.2, прогнано на стенде 2026-10-22
"""Что делает клиент со старыми настройками classic при group.protocol=consumer.

Для каждой настройки создаётся потребитель, подписывается и 8 секунд читает. Печатается,
упал ли конструктор, что пришло в error_cb и какие предупреждения написал librdkafka.
В конце то же для Java-клиента: kafka-console-consumer.sh внутри контейнера kafka1.

Запуск: python old_settings_trap.py
"""

import logging
import subprocess
import time

from confluent_kafka import Consumer, KafkaException

from producer_load import BOOTSTRAP, TOPIC, ensure_topic

CASES = [
    ("без лишних настроек", {}),
    ("session.timeout.ms=10000", {"session.timeout.ms": 10000}),
    ("heartbeat.interval.ms=1000", {"heartbeat.interval.ms": 1000}),
    ("partition.assignment.strategy=cooperative-sticky",
     {"partition.assignment.strategy": "cooperative-sticky"}),
    ("group.remote.assignor=range", {"group.remote.assignor": "range"}),
    ("group.remote.assignor=sticky (нет на брокере)", {"group.remote.assignor": "sticky"}),
]


class Collect(logging.Handler):
    """Собирает предупреждения librdkafka, которые клиент пишет в logger."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def try_python(title: str, extra: dict) -> None:
    print(f"\n--- python: {title}")
    log = logging.getLogger(f"rdkafka.{len(title)}.{time.time()}")
    handler = Collect()
    log.addHandler(handler)
    log.propagate = False
    errors = []
    conf = {"bootstrap.servers": BOOTSTRAP, "group.id": f"trap-{int(time.time() * 1000)}",
            "group.protocol": "consumer", "auto.offset.reset": "latest",
            "error_cb": lambda e: errors.append(str(e)), "logger": log, **extra}
    try:
        c = Consumer(conf)
    except KafkaException as e:
        print("  конструктор упал:", e.args[0])
        return
    assigned = []
    c.subscribe([TOPIC], on_assign=lambda _c, ps: assigned.extend(p.partition for p in ps))
    t = time.time()
    while time.time() - t < 8:
        msg = c.poll(0.2)
        if msg is not None and msg.error():
            errors.append(str(msg.error()))
    c.close()
    print(f"  назначено партиций: {len(set(assigned))}")
    for e in dict.fromkeys(errors):
        print("  ошибка:", e)
    for ln in dict.fromkeys(handler.lines):
        print("  лог:", ln[:220])


def try_java(title: str, props: list) -> None:
    print(f"\n--- java kafka-console-consumer: {title}")
    cmd = ["docker", "compose", "exec", "-T", "kafka1", "/opt/kafka/bin/kafka-console-consumer.sh",
           "--bootstrap-server", "localhost:19092", "--topic", TOPIC, "--group", f"trap-java-{int(time.time())}",
           "--timeout-ms", "6000", "--max-messages", "1", "--consumer-property", "group.protocol=consumer"]
    for p in props:
        cmd += ["--consumer-property", p]
    res = subprocess.run(cmd, capture_output=True, text=True)
    lines = [ln for ln in (res.stdout + res.stderr).splitlines()
             if any(w in ln for w in ("Exception", "ERROR", "WARN", "Processed"))]
    print(f"  код выхода {res.returncode}")
    for ln in lines[:4]:
        print("  ", ln[:220])


def main() -> None:
    ensure_topic()
    for title, extra in CASES:
        try_python(title, extra)
    try_java("session.timeout.ms=10000", ["session.timeout.ms=10000"])
    try_java("partition.assignment.strategy=CooperativeStickyAssignor",
             ["partition.assignment.strategy=org.apache.kafka.clients.consumer.CooperativeStickyAssignor"])


if __name__ == "__main__":
    main()
