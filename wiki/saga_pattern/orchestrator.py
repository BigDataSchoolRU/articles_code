# psycopg 3.3.8, postgres 18.6, прогнано на стенде 2026-11-12
"""Оркестратор саги с журналом состояния в своей базе `saga`.

После каждой локальной транзакции сервиса оркестратор пишет шаг в журнал. Между коммитом шага
в базе сервиса и записью в журнал есть окно: если процесс упадёт в нём, после рестарта журнал
не знает, что шаг выполнен, и повторит его. Поэтому шаги обязаны быть идемпотентными.
"""
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import services as s


@dataclass
class Step:
    name: str
    action: Callable
    compensation: Optional[Callable]
    kind: str  # compensable | pivot | retryable


# Порядок шагов: всё компенсируемое до pivot, после pivot только повторяемое
STEPS = [
    Step("create_order", s.create_order, s.cancel_order, "compensable"),
    Step("reserve_stock", s.reserve_stock, s.release_stock, "compensable"),
    Step("charge_payment", s.charge_payment, None, "pivot"),
    Step("commit_reservation", s.commit_reservation, None, "retryable"),
    Step("confirm_order", s.confirm_order, None, "retryable"),
]


class Orchestrator:
    def __init__(self, idempotent=True, semantic_lock=False, crash_after=None,
                 faults=None, hooks=None, retries=8, backoff=0.2, t0=None):
        self.idempotent = idempotent        # стабильный ключ шага или новый на каждую попытку
        self.semantic_lock = semantic_lock  # склад отличает «занято сагой» от «нет товара»
        self.crash_after = crash_after      # имя шага: упасть после его коммита, до записи в журнал
        self.faults = dict(faults or {})    # имя шага -> сколько раз бросить временный сбой
        self.hooks = hooks or {}            # 'after:<шаг>' и 'retry:<шаг>' -> функция(saga_id)
        self.retries, self.backoff = retries, backoff
        self.t0 = t0 or time.monotonic()

    # ── журнал ──────────────────────────────────────────────────────────────
    def say(self, saga_id, msg):
        print(f"  {time.monotonic() - self.t0:6.2f}s [{saga_id}] {msg}", flush=True)

    def record(self, saga_id, step, action, status, detail):
        with s.connect("saga") as conn:
            conn.execute(
                "INSERT INTO saga_log (saga_id, step, action, status, detail) "
                "VALUES (%s, %s, %s, %s, %s)",
                (saga_id, step, action, status, detail),
            )
        self.say(saga_id, f"{step:<19}{action:<11}{status:<7}{detail}")

    def set_state(self, saga_id, state):
        with s.connect("saga") as conn:
            conn.execute(
                "UPDATE saga_instances SET state = %s, updated_at = now() WHERE saga_id = %s",
                (state, saga_id),
            )
        self.say(saga_id, f"сага -> {state}")

    def idem_key(self, saga_id, step):
        if self.idempotent:
            return f"{saga_id}:{step}"
        # ошибка, которую показывает сценарий crash: ключ генерируется на каждую попытку
        return f"{saga_id}:{step}:{uuid.uuid4().hex[:6]}"

    # ── выполнение ──────────────────────────────────────────────────────────
    def start(self, saga_id, payload):
        with s.connect("saga") as conn:
            conn.execute(
                "INSERT INTO saga_instances (saga_id, payload, state) VALUES (%s, %s, 'RUNNING')",
                (saga_id, json.dumps(payload)),
            )
        self.say(saga_id, f"сага -> RUNNING {payload}")
        return self.resume(saga_id)

    def resume(self, saga_id):
        with s.connect("saga") as conn:
            payload, state = conn.execute(
                "SELECT payload, state FROM saga_instances WHERE saga_id = %s", (saga_id,)
            ).fetchone()
            done = {r[0] for r in conn.execute(
                "SELECT step FROM saga_log WHERE saga_id = %s AND action = 'DO' AND status = 'DONE'",
                (saga_id,),
            )}
        if state == "COMPENSATING":
            return self.compensate(saga_id, payload)
        if state != "RUNNING":
            return state
        for step in STEPS:
            if step.name in done:
                continue
            try:
                detail = self.call(saga_id, step, payload)
            except s.BusinessError as e:
                self.record(saga_id, step.name, "DO", "FAILED", str(e))
                self.set_state(saga_id, "COMPENSATING")
                return self.compensate(saga_id, payload)
            except s.TransientError as e:
                # повторы исчерпаны: сага остаётся RUNNING, её подберёт recover()
                self.say(saga_id, f"{step.name}: повторы исчерпаны ({e}), сага остаётся RUNNING")
                return "RUNNING"
            if self.crash_after == step.name:
                self.say(saga_id, f"{step.name} закоммичен в базе сервиса, оркестратор падает "
                                  f"до записи в журнал")
                os._exit(1)
            self.record(saga_id, step.name, "DO", "DONE", detail)
            if f"after:{step.name}" in self.hooks:
                self.hooks[f"after:{step.name}"](saga_id)
        self.set_state(saga_id, "COMPLETED")
        return "COMPLETED"

    def call(self, saga_id, step, payload):
        # временный сбой повторяется с паузой; бизнес-ошибка уходит наверх сразу
        key = self.idem_key(saga_id, step.name)
        for attempt in range(1, self.retries + 1):
            try:
                if self.faults.get(step.name, 0) > 0:
                    self.faults[step.name] -= 1
                    raise s.TransientError("таймаут ответа сервиса")
                if step.name == "reserve_stock":
                    return step.action(saga_id, payload, key, semantic_lock=self.semantic_lock)
                return step.action(saga_id, payload, key)
            except s.TransientError as e:
                self.say(saga_id, f"{step.name}: попытка {attempt} не прошла ({e}), повтор")
                if f"retry:{step.name}" in self.hooks:
                    self.hooks[f"retry:{step.name}"](saga_id)
                if attempt == self.retries:
                    raise
                time.sleep(self.backoff)
                if not self.idempotent:
                    key = self.idem_key(saga_id, step.name)

    def compensate(self, saga_id, payload):
        # компенсации идут в обратном порядке по шагам, которые журнал знает как выполненные
        with s.connect("saga") as conn:
            rows = conn.execute(
                "SELECT step, action FROM saga_log WHERE saga_id = %s AND status = 'DONE'",
                (saga_id,),
            ).fetchall()
        done = {st for st, act in rows if act == "DO"}
        undone = {st for st, act in rows if act == "COMPENSATE"}
        for step in reversed(STEPS):
            if step.compensation and step.name in done and step.name not in undone:
                detail = step.compensation(saga_id, payload)
                self.record(saga_id, step.name, "COMPENSATE", "DONE", detail)
        self.set_state(saga_id, "COMPENSATED")
        return "COMPENSATED"


def recover(orch: Orchestrator):
    """Рестарт оркестратора: дочитать журнал и довести каждую незавершённую сагу."""
    with s.connect("saga") as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT saga_id FROM saga_instances WHERE state IN ('RUNNING', 'COMPENSATING') "
            "ORDER BY saga_id"
        )]
    print(f"  recover: незавершённых саг в журнале {len(ids)}: {ids}", flush=True)
    return {sid: orch.resume(sid) for sid in ids}
