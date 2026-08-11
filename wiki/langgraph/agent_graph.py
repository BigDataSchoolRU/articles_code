# протестировано для langgraph 1.2.11, langchain-ollama 1.1.0, Ollama 0.32.9, Python 3.14
"""Минимальный граф агента на LangGraph: состояние, узел модели, узел инструментов и цикл между ними."""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, TypedDict

from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

# Модель и адрес Ollama выносим в переменные окружения, чтобы код не был прибит к одной модели
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Локальный справочник вместо похода во внешнюю систему: прогон должен быть воспроизводимым
# Данные по курсу AGENT взяты со страницы курса bigdataschool.ru на 20.04.2026
COURSES = {
    "AGENT": {
        "title": "ИИ агенты для оптимизации бизнес-процессов",
        "price_rub": 66000,
        "days": 6,
    }
}


@tool
def course_info(code: str) -> str:
    """Вернуть данные курса BigDataSchool по коду: название, стоимость в рублях и длительность в днях."""
    item = COURSES.get(code.strip().upper())
    if item is None:
        # Инструмент не бросает исключение, а возвращает читаемую ошибку: модель сможет её обработать
        return json.dumps(
            {"error": f"курс {code} не найден", "known_codes": sorted(COURSES)},
            ensure_ascii=False,
        )
    return json.dumps(item, ensure_ascii=False)


TOOLS = [course_info]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


class AgentState(TypedDict):
    """Состояние графа. Редьюсер add_messages дописывает новые сообщения, а не затирает список."""

    messages: Annotated[list, add_messages]


def build_model() -> ChatOllama:
    """Локальная модель через Ollama. temperature и seed зафиксированы ради воспроизводимости прогона."""
    return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_URL, temperature=0, seed=0)


def build_graph(model: Any = None):
    """Собрать и скомпилировать граф. Модель передаётся аргументом, чтобы её можно было подменить в тестах."""
    bound = (model or build_model()).bind_tools(TOOLS)

    def call_model(state: AgentState) -> dict:
        # Узел модели: отдаём всю историю сообщений и возвращаем ответ одним элементом списка
        return {"messages": [bound.invoke(state["messages"])]}

    def call_tools(state: AgentState) -> dict:
        # Узел инструментов: выполняем каждый вызов, который запросила модель
        last = state["messages"][-1]
        results = []
        for call in last.tool_calls:
            output = TOOLS_BY_NAME[call["name"]].invoke(call["args"])
            results.append(ToolMessage(content=output, tool_call_id=call["id"]))
        return {"messages": results}

    def should_continue(state: AgentState) -> str:
        # Условное ребро: пока модель просит инструменты, крутимся в цикле, иначе выходим
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", call_tools)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile()


if __name__ == "__main__":
    graph = build_graph()
    question = "Сколько стоит курс AGENT и сколько дней он идёт?"
    state = graph.invoke({"messages": [{"role": "user", "content": question}]})
    for message in state["messages"]:
        message.pretty_print()

