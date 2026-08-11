# протестировано для langgraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1, langchain-ollama 1.1.0, Ollama 0.32.9, Python 3.14
"""Тот же граф агента, но с чекпоинтером SQLite и паузой на подтверждение человека через interrupt."""

from __future__ import annotations

import os
import sqlite3
from typing import Annotated, Any, TypedDict

from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DB_PATH = os.getenv("LANGGRAPH_DB", "langgraph_demo.db")


@tool
def submit_request(course_code: str, people: int) -> str:
    """Отправить заявку на обучение группы сотрудников по коду курса. Требует подтверждения человека."""
    # Пауза до подтверждения. Значение уедет вызывающей стороне, граф встанет и дождётся ответа
    decision = interrupt(
        {
            "action": "submit_request",
            "course_code": course_code,
            "people": people,
            "question": "Отправляем заявку?",
        }
    )
    # Побочный эффект стоит после interrupt: узел перезапускается целиком, и до паузы код выполнится повторно
    if decision is True:
        return f"Заявка отправлена: курс {course_code}, участников {people}"
    return "Заявка отменена человеком"


TOOLS = [submit_request]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


class AgentState(TypedDict):
    """Состояние графа. Редьюсер add_messages дописывает новые сообщения в конец истории."""

    messages: Annotated[list, add_messages]


def build_model() -> ChatOllama:
    """Локальная модель через Ollama с зафиксированными temperature и seed."""
    return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL, temperature=0, seed=0)


def build_graph(checkpointer: Any, model: Any = None):
    """Собрать граф и скомпилировать его с чекпоинтером: без него interrupt работать не будет."""
    bound = (model or build_model()).bind_tools(TOOLS)

    def call_model(state: AgentState) -> dict:
        return {"messages": [bound.invoke(state["messages"])]}

    def call_tools(state: AgentState) -> dict:
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            output = TOOLS_BY_NAME[call["name"]].invoke(call["args"])
            results.append(ToolMessage(content=output, tool_call_id=call["id"]))
        return {"messages": results}

    def should_continue(state: AgentState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", call_tools)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    graph = build_graph(SqliteSaver(connection))

    # thread_id это указатель на состояние: с тем же значением граф продолжит прерванный прогон
    config = {"configurable": {"thread_id": "demo-1"}}
    question = "Оформи заявку на курс AGENT для 3 сотрудников"

    first = graph.invoke({"messages": [{"role": "user", "content": question}]}, config)
    print("ПАУЗА НА ПОДТВЕРЖДЕНИЕ:", first["__interrupt__"])

    snapshot = graph.get_state(config)
    print("СЛЕДУЮЩИЙ УЗЕЛ ПОСЛЕ ВОЗОБНОВЛЕНИЯ:", snapshot.next)

    # Возобновляем тот же поток: значение resume станет результатом вызова interrupt внутри инструмента
    final = graph.invoke(Command(resume=True), config)
    for message in final["messages"]:
        message.pretty_print()

    print("ЧЕКПОИНТОВ В ПОТОКЕ:", len(list(graph.get_state_history(config))))
    connection.close()
