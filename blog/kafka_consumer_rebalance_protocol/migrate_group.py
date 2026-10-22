# confluent-kafka 2.16.0, Apache Kafka 4.3.2, прогнано на стенде 2026-10-22
"""Онлайн-миграция живой группы с classic на consumer (KIP-848) поочерёдным перезапуском.

Группа из 4 участников classic с cooperative-sticky читает под нагрузкой. Участники по одному
выходят и возвращаются с group.protocol=consumer. После каждого шага печатаются тип группы
(kafka-groups.sh --list), участники с флагом UPGRADED и пауза в чтении на этом шаге.
Команды CLI выполняются в контейнере kafka1 через docker compose exec.

Запуск: python migrate_group.py
"""

import subprocess
import threading
import time

import producer_load
from group_member import Group


def cli(tool: str, *args: str) -> str:
    cmd = ["docker", "compose", "exec", "-T", "kafka1", f"/opt/kafka/bin/{tool}",
           "--bootstrap-server", "localhost:19092", *args]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.rstrip()


def show(group: str) -> None:
    # Тип и протокол группы: Classic или Consumer
    lines = cli("kafka-groups.sh", "--list").splitlines()
    print("\n".join(ln for ln in lines if ln.startswith(("GROUP", group))))
    # Участники: у consumer-группы видно эпоху и кто уже на новом протоколе (UPGRADED)
    print(cli("kafka-consumer-groups.sh", "--describe", "--group", group, "--members", "--verbose"))


def step_report(name: str, res: dict) -> None:
    print(f"  пауза: остановлено {res['stalled']}/12, макс. {res['max_pause']} с, "
          f"сумма {res['stall_sum']} парт.·с, отозвано {res['revoked']}", flush=True)


def main() -> None:
    stop = threading.Event()
    threading.Thread(target=producer_load.run, args=(stop,), daemon=True).start()
    time.sleep(3)

    g = Group(f"migrate-{int(time.time())}")
    for i in range(1, 5):
        g.start("cooperative", f"m{i}")
    g.wait_stable(90)
    time.sleep(3)
    g.window(0, time.time())
    print("=== ШАГ 0: все четыре участника на classic, cooperative-sticky ===")
    show(g.group)

    for i in range(1, 5):
        name = f"m{i}"
        t0 = time.time()
        g.leave(name)                # мягкий выход старого клиента
        g.start("consumer", name)    # тот же код, но group.protocol=consumer
        time.sleep(12)
        g.wait_stable(60)
        time.sleep(2)
        print(f"\n=== ШАГ {i}: {name} перезапущен с group.protocol=consumer, "
              f"на новом протоколе {i} из 4 ===")
        step_report(name, g.window(t0, time.time()))
        show(g.group)

    g.stop_all()
    time.sleep(2)
    print("\n=== ПОСЛЕ ВЫХОДА ВСЕХ: пустая группа ===")
    show(g.group)
    stop.set()


if __name__ == "__main__":
    main()
