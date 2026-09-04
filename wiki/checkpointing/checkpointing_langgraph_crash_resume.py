# langgraph 1.2.11, langgraph-checkpoint 4.2.0, langgraph-checkpoint-sqlite 3.1.1
# прогнано на стенде 2026-09-04
"""
Демо: аварийное прерывание процесса посередине графа LangGraph и восстановление
по одному и тому же thread_id из SQLite-чекпоинтера.

Идея: главный процесс дважды запускает себя же отдельным процессом (subprocess) в
режиме --worker. Первый запуск падает по-настоящему (os._exit внутри узла графа,
как убитый процесс, а не пойманное исключение). Второй запуск с тем же thread_id
продолжает граф с последнего сохранённого чекпоинта.
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

WORKDIR = Path(__file__).resolve().parent
DB_PATH = WORKDIR / "checkpoint_demo.db"
EFFECT_LOG = WORKDIR / "external_effect.log"
THREAD_ID = "checkpointing-demo"


class State(TypedDict):
    steps: list[str]


def build_graph(checkpointer):
    def step1(state: State) -> State:
        return {"steps": state["steps"] + ["step1"]}

    def step2(state: State) -> State:
        return {"steps": state["steps"] + ["step2"]}

    def step3_external_call(state: State) -> State:
        # имитация вызова внешнего сервиса с side effect (например, отправка письма).
        # Пишем в лог ДО того, как узел успеет отдать результат обратно графу.
        # Номер попытки считаем по числу уже записанных строк, а не по состоянию
        # графа: state["steps"] между попытками не меняется (обе попытки читают
        # чекпоинт после step2), а лог должен показать реальное число вызовов.
        attempt_number = 1
        if EFFECT_LOG.exists():
            attempt_number = len(EFFECT_LOG.read_text().splitlines()) + 1
        with open(EFFECT_LOG, "a") as f:
            f.write(f"внешний вызов из step3, попытка №{attempt_number}\n")
        if os.environ.get("CRASH_HERE") == "1":
            # реальное убийство процесса (аналог kill -9), а не Python-исключение:
            # LangGraph не успевает получить возврат узла и зафиксировать чекпоинт
            os._exit(137)
        return {"steps": state["steps"] + ["step3"]}

    def step4(state: State) -> State:
        return {"steps": state["steps"] + ["step4"]}

    graph = StateGraph(State)
    graph.add_node("step1", step1)
    graph.add_node("step2", step2)
    graph.add_node("step3", step3_external_call)
    graph.add_node("step4", step4)
    graph.add_edge(START, "step1")
    graph.add_edge("step1", "step2")
    graph.add_edge("step2", "step3")
    graph.add_edge("step3", "step4")
    graph.add_edge("step4", END)
    return graph.compile(checkpointer=checkpointer)


def run_worker(crash: bool) -> None:
    with SqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        app = build_graph(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}
        if crash:
            os.environ["CRASH_HERE"] = "1"
        state_before = app.get_state(config)
        # пустое состояние треда - первый запуск, иначе - продолжение с чекпоинта
        input_data = {"steps": []} if not state_before.values else None
        # durability="sync" - чекпоинт каждого шага пишется на диск синхронно,
        # до перехода к следующему узлу. Без явного durability действует
        # значение по умолчанию "async": запись уходит в фон, и при таком же
        # os._exit чекпоинт после step2 рискует не успеть долететь до диска.
        app.invoke(input_data, config, durability="sync")
        print("узел step4 отработал, процесс завершается штатно")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        run_worker(crash="--crash" in sys.argv)
        sys.exit(0)

    for path in (DB_PATH, EFFECT_LOG):
        path.unlink(missing_ok=True)

    print("=== Попытка 1: запускаем граф, step3 аварийно убьёт процесс ===")
    # sys.stdout.flush() перед subprocess.run обязателен: при редиректе в файл
    # (как делает selfcheck.sh) stdout родителя блочно буферизуется, а не
    # построчно, как в терминале. Без явного flush дочерний процесс успевает
    # записать и сбросить свой вывод раньше, чем накопленный буфер родителя,
    # и в run_output.txt строки появляются не в хронологическом порядке.
    sys.stdout.flush()
    result = subprocess.run([sys.executable, __file__, "--worker", "--crash"])
    print(f"процесс упал с кодом {result.returncode} (137 = убит сигналом, не поймано)")

    print("\n=== Что реально сохранилось в чекпоинтере после падения ===")
    with SqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        app = build_graph(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}
        snapshot = app.get_state(config)
        print("сохранённые шаги:", snapshot.values["steps"])
        print("следующий узел к выполнению:", snapshot.next)

    print("\n=== Попытка 2: новый процесс, тот же thread_id ===")
    sys.stdout.flush()
    result = subprocess.run([sys.executable, __file__, "--worker"])
    print(f"процесс завершился кодом {result.returncode}")

    print("\n=== Итоговое состояние после resume ===")
    with SqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        app = build_graph(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}
        snapshot = app.get_state(config)
        print("шаги:", snapshot.values["steps"])

    print("\n=== Лог внешнего эффекта step3 (побочный эффект не под чекпоинтом) ===")
    print(EFFECT_LOG.read_text().rstrip())
