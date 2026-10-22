# confluent-kafka 2.16.0, Apache Kafka 4.3.2, прогнано на стенде 2026-10-22
"""Участник группы потребителей и сборщик замеров для rebalance_bench.py и migrate_group.py.

Каждый участник живёт в своём процессе: так его можно честно убить SIGKILL, как падение
пода. Всё, что он видит, уходит в общую очередь: пачки сообщений и колбэки
on_assign / on_revoke / on_lost. Сборщик в главном процессе считает паузу по партициям.
"""

import multiprocessing as mp
import threading
import time
from collections import defaultdict

from producer_load import BOOTSTRAP, PARTITIONS, TOPIC

# Четыре варианта из статьи. Тайм-аут сессии у classic задаёт клиент (10 с),
# у consumer его задаёт брокер (group.consumer.session.timeout.ms=10000 в compose.yaml).
MODES = {
    "eager": {"group.protocol": "classic", "partition.assignment.strategy": "range",
              "session.timeout.ms": 10000},
    "cooperative": {"group.protocol": "classic", "partition.assignment.strategy": "cooperative-sticky",
                    "session.timeout.ms": 10000},
    "static": {"group.protocol": "classic", "partition.assignment.strategy": "cooperative-sticky",
               "session.timeout.ms": 10000},  # плюс group.instance.id, см. member()
    "consumer": {"group.protocol": "consumer"},  # тайминги и assignor (uniform) на брокере
    "consumer_hb1s": {"group.protocol": "consumer"},  # то же, heartbeat группы 1 с, см. GROUP_CONFIGS
}
# Настройки уровня группы (KIP-848): живут на брокере, клиент их не передаёт
GROUP_CONFIGS = {"consumer_hb1s": {"consumer.heartbeat.interval.ms": "1000"}}

STALL = 1.0  # партиция считается остановленной, если задержка чтения выше секунды


def member(mode: str, name: str, group: str, stop, q) -> None:
    """Процесс одного потребителя: читает и шлёт в очередь всё, что видит."""
    from confluent_kafka import Consumer

    conf = {"bootstrap.servers": BOOTSTRAP, "group.id": group, "client.id": name,
            "auto.offset.reset": "latest", **MODES[mode]}
    if mode == "static":
        conf["group.instance.id"] = name  # статическое членство: id переживает рестарт
    c = Consumer(conf)

    def cb(kind):
        return lambda _c, parts: q.put((kind, name, time.time(), [p.partition for p in parts]))

    c.subscribe([TOPIC], on_assign=cb("assign"), on_revoke=cb("revoke"), on_lost=cb("lost"))
    while not stop.is_set():
        msgs = c.consume(500, 0.1)
        now = time.time()
        batch = [(m.partition(), m.offset(), m.timestamp()[1]) for m in msgs if not m.error()]
        if batch:
            q.put(("batch", name, now, batch))
    c.close()  # мягкий выход: LeaveGroup у classic, heartbeat с epoch -1 у consumer


def set_group_config(group: str, configs: dict) -> None:
    """IncrementalAlterConfigs для ресурса GROUP: так меняют тайминги без перезапуска брокера."""
    from confluent_kafka.admin import (AdminClient, AlterConfigOpType, ConfigEntry,
                                       ConfigResource, ResourceType)

    entries = [ConfigEntry(k, v, incremental_operation=AlterConfigOpType.SET) for k, v in configs.items()]
    res = ConfigResource(ResourceType.GROUP, group, incremental_configs=entries)
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})  # ссылка нужна до конца result()
    admin.incremental_alter_configs([res])[res].result()


class Group:
    """Набор участников-процессов одной группы и сборщик их событий."""

    def __init__(self, group: str):
        self.ctx = mp.get_context("spawn")
        self.q = self.ctx.Queue()
        self.group = group
        self.procs = {}  # имя -> (процесс, событие остановки)
        self.owned = defaultdict(set)  # имя -> партиции по колбэкам
        self.last_cb = time.time()
        self.max_off = {}  # партиция -> максимальный прочитанный offset
        self.events = []  # (время, вид, имя, данные)
        self.lock = threading.Lock()
        threading.Thread(target=self._drain, daemon=True).start()

    def start(self, mode: str, name: str) -> None:
        stop = self.ctx.Event()
        p = self.ctx.Process(target=member, args=(mode, name, self.group, stop, self.q), daemon=True)
        p.start()
        self.procs[name] = (p, stop)

    def leave(self, name: str) -> None:
        p, stop = self.procs.pop(name)
        stop.set()
        p.join(30)

    def kill(self, name: str) -> None:
        p, _ = self.procs.pop(name)
        p.kill()  # SIGKILL: ни LeaveGroup, ни колбэков, брокер узнает по тайм-ауту сессии
        p.join()
        with self.lock:
            self.owned.pop(name, None)

    def stop_all(self) -> None:
        for name in list(self.procs):
            self.leave(name)

    def _drain(self) -> None:
        while True:
            kind, name, t, data = self.q.get()
            with self.lock:
                if kind == "batch":
                    self.events.append((t, kind, name, data))
                    continue
                self.last_cb = t
                if kind == "assign":
                    self.owned[name] |= set(data)
                else:  # revoke и lost
                    self.owned[name] -= set(data)
                self.events.append((t, kind, name, data))

    def stable(self) -> bool:
        """Все 12 партиций розданы ровно по разу, у каждого живого участника есть партиции,
        колбэков 3 с не было."""
        with self.lock:
            alive = [self.owned[n] for n in self.procs]
            total = sum(len(s) for s in alive)
            union = set().union(*alive) if alive else set()
            return (total == PARTITIONS and len(union) == PARTITIONS and all(alive)
                    and time.time() - self.last_cb > 3)

    def wait_stable(self, timeout: float = 60) -> float:
        t0 = time.time()
        while not self.stable() and time.time() - t0 < timeout:
            time.sleep(0.2)
        return time.time() - t0

    def window(self, t0: float, t1: float) -> dict:
        """Замер окна [t0, t1]: пауза по партициям, отзывы и повторно прочитанные сообщения."""
        pause = defaultdict(float)
        dup = 0
        revoked, revokers, lost = 0, set(), 0
        cb_times = []
        with self.lock:
            evs = [e for e in self.events if e[0] >= t0 - 0.5]
            self.events = [e for e in self.events if e[0] >= t1]  # память не копим
        for t, kind, name, data in sorted(evs, key=lambda e: e[0]):
            if kind == "batch":
                for p, off, ts in data:
                    if off <= self.max_off.get(p, -1):
                        dup += t >= t0  # повтор после падения: offset ещё не был зафиксирован
                        continue
                    self.max_off[p] = off
                    if t0 <= t <= t1:
                        pause[p] = max(pause[p], t - ts / 1000)
                continue
            if not t0 <= t <= t1:
                continue
            cb_times.append(t)
            if kind == "revoke":
                revoked += len(data)
                revokers.add(name)
            elif kind == "lost":
                lost += len(data)
        stalled = {p: v for p, v in pause.items() if v > STALL}
        return {
            "stalled": len(stalled),
            "max_pause": round(max(pause.values(), default=0.0), 2),
            "stall_sum": round(sum(stalled.values()), 1),
            "revoked": revoked,
            "revokers": len(revokers),
            "lost": lost,
            "dup": dup,
            "cb_span": round(cb_times[-1] - cb_times[0], 2) if cb_times else 0.0,
        }
