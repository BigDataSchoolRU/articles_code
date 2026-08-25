# LangGraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1, langchain-ollama 1.1.0,
# Ollama 0.32.13, модель qwen2.5:7b. Прогнано на стенде 2026-08-25.
# Supervisor-граф: управляющий узел выбирает исполнителя, состояние после каждого
# суперстепа уходит в чекпоинтер SQLite.

import os
import sqlite3
import time
from typing import Annotated, TypedDict

from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoints.sqlite")
MODEL = "qwen2.5:7b"
ROLES = ("researcher", "writer")


def append(left: list, right: list) -> list:
    """Редьюсер общего состояния: узлы дописывают в журнал, а не затирают его."""
    return (left or []) + (right or [])


class OrchestrationState(TypedDict):
    """Общее состояние графа. Его снимок и попадает в чекпоинтер после каждого шага."""
    task: str
    notes: str
    draft: str
    trace: Annotated[list, append]


llm = ChatOllama(model=MODEL, temperature=0)


def supervisor(state: OrchestrationState) -> Command:
    """Управляющий узел. Спрашивает модель, кого звать следующим, и возвращает
    Command с полем goto: это и есть маршрутизация внутри графа."""
    done = []
    if state.get("notes"):
        done.append("researcher")
    if state.get("draft"):
        done.append("writer")

    prompt = (
        "Ты диспетчер конвейера из двух исполнителей.\n"
        f"researcher собирает факты, writer пишет текст по фактам.\n"
        f"Задача: {state['task']}\n"
        f"Уже отработали: {', '.join(done) if done else 'никто'}\n"
        "Ответь ровно одним словом из списка: researcher, writer, done."
    )
    t0 = time.time()
    raw = llm.invoke(prompt).content.strip().lower()
    took = round(time.time() - t0, 2)

    # Проверка предусловий. Локальная модель регулярно предлагает writer до того,
    # как researcher собрал факты. Оркестратор обязан такой маршрут отклонить:
    # порядок шагов это его зона ответственности, а не модели.
    def valid(name: str) -> bool:
        if name == "researcher":
            return not state.get("notes")
        if name == "writer":
            return bool(state.get("notes")) and not state.get("draft")
        return bool(state.get("notes")) and bool(state.get("draft"))

    choice = next((r for r in (*ROLES, "done") if r in raw), None)
    fallback = ""
    if choice is None or not valid(choice):
        rejected = choice or f"ответ '{raw[:30]}'"
        choice = "researcher" if not state.get("notes") else ("writer" if not state.get("draft") else "done")
        fallback = f" (модель предложила {rejected}, маршрут отклонён по предусловию)"

    line = f"supervisor -> {choice} за {took} с{fallback}"
    print("[граф]", line)
    goto = END if choice == "done" else choice
    return Command(goto=goto, update={"trace": [line]})


def researcher(state: OrchestrationState) -> dict:
    """Первый исполнитель. Возвращает только свой кусок состояния."""
    t0 = time.time()
    text = llm.invoke(
        f"Задача: {state['task']}\nДай ровно три коротких тезиса, по одному в строке, без вступления."
    ).content.strip()
    took = round(time.time() - t0, 2)
    print(f"[граф] researcher отработал за {took} с, {len(text)} символов")
    return {"notes": text, "trace": [f"researcher: {took} с"]}


def writer(state: OrchestrationState) -> dict:
    """Второй исполнитель. Видит результат первого через общее состояние,
    а не через прямой вызов: агенты между собой не общаются."""
    t0 = time.time()
    text = llm.invoke(
        f"Задача: {state['task']}\nТезисы:\n{state['notes']}\n"
        "Напиши один абзац на 3-4 предложения по этим тезисам."
    ).content.strip()
    took = round(time.time() - t0, 2)
    print(f"[граф] writer отработал за {took} с, {len(text)} символов")
    return {"draft": text, "trace": [f"writer: {took} с"]}


def build_graph(checkpointer):
    """Сборка графа. Ребра от исполнителей ведут назад в супервизор,
    поэтому управление всегда возвращается в одну точку."""
    g = StateGraph(OrchestrationState)
    g.add_node("supervisor", supervisor)
    g.add_node("researcher", researcher)
    g.add_node("writer", writer)
    g.add_edge(START, "supervisor")
    g.add_edge("researcher", "supervisor")
    g.add_edge("writer", "supervisor")
    return g.compile(checkpointer=checkpointer)


def main():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    graph = build_graph(checkpointer)

    thread_id = "demo-supervisor"
    config = {"configurable": {"thread_id": thread_id}}
    task = "Чем оркестрация ИИ отличается от обычного вызова языковой модели из кода приложения"

    print(f"=== прогон графа, thread_id={thread_id} ===")
    t0 = time.time()
    # durability='sync' пишет снимок состояния до возврата управления:
    # так чекпоинт переживёт обрыв процесса ровно на этом шаге.
    for step, snapshot in enumerate(
        graph.stream({"task": task, "notes": "", "draft": "", "trace": []},
                     config, stream_mode="values", durability="sync"), start=1):
        print(f"[суперстеп {step}] notes={len(snapshot.get('notes',''))} симв., "
              f"draft={len(snapshot.get('draft',''))} симв., шагов в журнале {len(snapshot.get('trace', []))}")
    total = round(time.time() - t0, 2)

    final = graph.get_state(config).values
    print(f"=== граф отработал за {total} с ===")
    print("--- журнал маршрутизации ---")
    for line in final["trace"]:
        print(" ", line)
    print("--- готовый текст ---")
    print(final["draft"])

    history = list(graph.get_state_history(config))
    print(f"--- чекпоинтов в SQLite по thread_id={thread_id}: {len(history)} ---")
    for snap in reversed(history):
        nxt = snap.next or ("END",)
        print(f"  {snap.config['configurable']['checkpoint_id'][:8]}  следующий узел: {','.join(nxt)}")
    print(f"размер файла чекпоинтов: {os.path.getsize(DB_PATH)} байт")
    conn.close()


if __name__ == "__main__":
    main()
