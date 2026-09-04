# dbos 2.31.0, PostgreSQL 18.4 (Homebrew), psycopg 3.3.4, прогнано на стенде 2026-09-04
"""
Ядро durable execution на примере DBOS: workflow из трёх шагов переживает
жёсткий крах процесса (kill -9 снаружи, между шагом 2 и шагом 3) и на
следующем запуске программы доигрывается сам — без единой строки кода вида
"восстанови меня с такого-то места".

Механика восстановления: DBOS.launch() при старте процесса сам находит
незавершённые workflow, которые ранее исполнял этот же executor
(по умолчанию executor_id == "local", стабилен между перезапусками), и
доигрывает их с прерванного места в фоновом потоке.

Проверяемое отличие от чекпоинтинга снимком состояния: шаги 1 и 2 не
выполняются повторно. Это видно по таблице side_effects — после краха и
восстановления там ровно одна строка на каждый шаг, а не две на первые два.

Запуск (подробности и вывод по шагам в RUNBOOK.md):
    python3 workflow_recovery_demo.py start &
    PID=$!
    sleep 2 && kill -9 $PID        # жёсткий крах между шагом 2 и шагом 3
    python3 workflow_recovery_demo.py recover
"""

import os
import sys
import time

import psycopg
from dbos import DBOS, DBOSConfig, SetWorkflowID

DEMO_DSN = "postgresql://techfriends@localhost:5432/durable_execution_demo"
WORKFLOW_ID = "order-42"  # фиксированный id, чтобы "recover" нашёл тот же workflow
ORDER_ID = "42"
SLEEP_WINDOW_SECONDS = 5  # окно, в которое снаружи прилетает kill -9

config: DBOSConfig = {
    "name": "durable_execution_demo",
    "system_database_url": DEMO_DSN,
}
DBOS(config=config)


def _log_side_effect(step_name: str) -> None:
    """Реальный побочный эффект шага — строка в прикладной таблице, а не
    просто возврат значения из функции. Повторное выполнение шага добавило
    бы вторую строку, и это станет видно в count_side_effects()."""
    with psycopg.connect(DEMO_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO side_effects (workflow_id, step_name, order_id) "
            "VALUES (%s, %s, %s)",
            (DBOS.workflow_id, step_name, ORDER_ID),
        )


@DBOS.step()
def charge_payment() -> None:
    print("шаг 1: списываем оплату", flush=True)
    _log_side_effect("charge_payment")


@DBOS.step()
def reserve_inventory() -> None:
    print("шаг 2: резервируем товар на складе", flush=True)
    _log_side_effect("reserve_inventory")


@DBOS.step()
def send_confirmation() -> None:
    print("шаг 3: отправляем подтверждение клиенту", flush=True)
    _log_side_effect("send_confirmation")


@DBOS.workflow()
def process_order() -> None:
    charge_payment()
    reserve_inventory()
    # DBOS.sleep, а не time.sleep: длительность паузы тоже часть durable-
    # состояния workflow, при восстановлении DBOS не будет спать заново то
    # время, что уже прошло с исходного старта.
    DBOS.sleep(SLEEP_WINDOW_SECONDS)
    send_confirmation()


def count_side_effects() -> dict[str, int]:
    with psycopg.connect(DEMO_DSN) as conn:
        rows = conn.execute(
            "SELECT step_name, count(*) FROM side_effects "
            "WHERE workflow_id = %s GROUP BY step_name ORDER BY step_name",
            (WORKFLOW_ID,),
        ).fetchall()
    return dict(rows)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "start"
    DBOS.launch()

    if mode == "start":
        print(f"PID={os.getpid()}", flush=True)
        with SetWorkflowID(WORKFLOW_ID):
            handle = DBOS.start_workflow(process_order)
        # Дожидаемся результата в первом процессе только если его не убьют
        # снаружи в течение SLEEP_WINDOW_SECONDS — по сценарию демо так и
        # происходит, эта ветка для контрольного запуска без kill -9.
        handle.get_result()
        print("workflow завершился без сбоя (контрольный прогон)", flush=True)
    elif mode == "recover":
        # DBOS.launch() уже поставил фоновое восстановление незавершённых
        # workflow предыдущего процесса. Ждём его исхода и проверяем результат.
        time.sleep(SLEEP_WINDOW_SECONDS + 2)
        status = DBOS.get_workflow_status(WORKFLOW_ID)
        print("статус workflow после восстановления:", status.status if status else None, flush=True)
        print("побочные эффекты по шагам:", count_side_effects(), flush=True)
    else:
        raise SystemExit(f"неизвестный режим: {mode} (start | recover)")


if __name__ == "__main__":
    main()
