# langgraph 1.2.11, langgraph-checkpoint 4.2.0, langgraph-checkpoint-sqlite 3.1.1
# прогнано на стенде 2026-09-04
"""
Демо: time travel в LangGraph - просмотр истории чекпоинтов треда и форк
выполнения от более раннего чекпоинта по настоящей другой ветке графа
(условный переход, а не просто другое значение в том же узле).
"""
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

WORKDIR = Path(__file__).resolve().parent
DB_PATH = WORKDIR / "time_travel_demo.db"
THREAD_ID = "time-travel-demo"


class State(TypedDict):
    log: list[str]
    path: Literal["main", "alt"]


def make_node(label: str):
    def node(state: State) -> State:
        return {"log": state["log"] + [label]}

    return node


def route_after_b(state: State) -> str:
    # выбор ветки читает state, записанный в чекпоинт - именно это поле
    # форк будет подменять, чтобы увести выполнение на другую ветку
    return "c_alt" if state["path"] == "alt" else "c_main"


def build_graph(checkpointer):
    graph = StateGraph(State)
    graph.add_node("a", make_node("a"))
    graph.add_node("b", make_node("b"))
    graph.add_node("c_main", make_node("c_main"))
    graph.add_node("c_alt", make_node("c_alt"))
    graph.add_node("d", make_node("d"))
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_conditional_edges("b", route_after_b, {"c_main": "c_main", "c_alt": "c_alt"})
    graph.add_edge("c_main", "d")
    graph.add_edge("c_alt", "d")
    graph.add_edge("d", END)
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    DB_PATH.unlink(missing_ok=True)

    with SqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        app = build_graph(checkpointer)
        config = {"configurable": {"thread_id": THREAD_ID}}

        print("=== Основной прогон: a -> b -> c_main -> d ===")
        final_state = app.invoke({"log": [], "path": "main"}, config)
        print("финальный лог основной ветки:", final_state["log"])
        original_final_checkpoint_id = app.get_state(config).config["configurable"]["checkpoint_id"]

        print("\n=== История чекпоинтов треда, от новых к старым ===")
        history = list(app.get_state_history(config))
        for snap in history:
            cid = snap.config["configurable"]["checkpoint_id"]
            print(f"checkpoint_id={cid[:8]}...  log={snap.values.get('log')}  next={snap.next}")

        # чекпоинт сразу после узла "b", до ветвления на c_main/c_alt
        checkpoint_after_b = next(s for s in history if s.values.get("log") == ["a", "b"])
        cid_after_b = checkpoint_after_b.config["configurable"]["checkpoint_id"]
        print(f"\nвыбран чекпоинт после узла 'b' для отката: {cid_after_b[:8]}...")

        print("\n=== Форк: та же точка отката, другая ветка через смену 'path' ===")
        # update_state с as_node="b" создаёт НОВЫЙ дочерний чекпоинт у checkpoint_after_b
        # и не трогает цепочку основной ветки (c_main, d) - у неё свой checkpoint_id.
        # Условный переход после "b" читает уже новое значение path и уводит на c_alt.
        fork_config = app.update_state(
            checkpoint_after_b.config,
            {"log": checkpoint_after_b.values["log"], "path": "alt"},
            as_node="b",
        )
        forked_state = app.invoke(None, fork_config)
        print("финальный лог форкнутой ветки:", forked_state["log"])

        print("\n=== Исходная ветка осталась доступна по своему checkpoint_id ===")
        original_snapshot = app.get_state(
            {"configurable": {"thread_id": THREAD_ID, "checkpoint_id": original_final_checkpoint_id}}
        )
        print("лог исходного финального чекпоинта:", original_snapshot.values["log"])

        print("\n=== У треда теперь два независимых финальных чекпоинта ===")
        all_ids_short = {snap.config["configurable"]["checkpoint_id"][:8] for snap in app.get_state_history(config)}
        print("исходный конечный checkpoint_id всё ещё в истории:", original_final_checkpoint_id[:8] in all_ids_short)
