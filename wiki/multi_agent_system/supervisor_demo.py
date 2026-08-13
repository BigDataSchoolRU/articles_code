# LangGraph 1.2.11, langchain-ollama 1.1.0, Python 3.12.13, Ollama 0.32.9, модель qwen2.5:7b. Прогнано на стенде.
"""Мультиагентная система с супервизором: подбор курса под запрос слушателя.

Четыре роли: супервизор решает, кто работает следующим, поисковик достаёт курсы
из каталога, аналитик формулирует рекомендацию, критик проверяет её на выдумки.
"""

import operator
from typing import Annotated, TypedDict

from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph

MODEL = "qwen2.5:7b"

# Локальный каталог вместо внешней базы: демо не должно зависеть от сети.
CATALOG = [
    {"code": "DEVKI", "title": "Apache Kafka для инженеров данных", "about": "потоковая передача, топики, продюсеры и консьюмеры"},
    {"code": "FLINK", "title": "Потоковая обработка данных с Apache Flink", "about": "стриминговые джобы, окна, состояние"},
    {"code": "AIRF", "title": "Apache Airflow для инженеров данных", "about": "пакетные пайплайны, DAG, расписания"},
    {"code": "AGENT", "title": "ИИ-агенты для оптимизации бизнес-процессов", "about": "LLM-агенты, инструменты, мультиагентные системы"},
]


class TeamState(TypedDict):
    """Общая память команды. Каждый агент дописывает своё поле, чужие не трогает."""
    request: str
    findings: str
    analysis: str
    review: str
    route_log: Annotated[list[str], operator.add]
    steps: int
    next: str


llm = ChatOllama(model=MODEL, temperature=0)


def ask(system: str, user: str) -> str:
    """Один вызов модели с системной ролью агента."""
    return llm.invoke([("system", system), ("human", user)]).content.strip()


def supervisor(state: TeamState) -> TeamState:
    """Супервизор не решает задачу, он только выбирает следующего исполнителя."""
    done = [k for k in ("findings", "analysis", "review") if state.get(k)]
    verdict = ask(
        "Ты диспетчер команды агентов. Отвечай ровно одним словом из списка: "
        "researcher, analyst, critic, FINISH. Без пояснений.",
        f"Запрос пользователя: {state['request']}\n"
        f"Уже готово: {done or 'ничего'}\n"
        "Порядок работы: сначала researcher, потом analyst, потом critic, потом FINISH.",
    )
    choice = next((r for r in ("researcher", "analyst", "critic", "FINISH") if r.lower() in verdict.lower()), None)
    # Предохранитель: модель на 7B миллиардов параметров иногда возвращает мусор
    # или зацикливает роль, поэтому детерминированный порядок остаётся страховкой.
    fallback = "researcher" if not state.get("findings") else "analyst" if not state.get("analysis") else "critic" if not state.get("review") else "FINISH"
    if choice is None or (choice != "FINISH" and state.get({"researcher": "findings", "analyst": "analysis", "critic": "review"}[choice])):
        choice = fallback
    return {
        "next": choice,
        "steps": state["steps"] + 1,
        "route_log": [f"supervisor -> {choice} (сырой ответ модели: {verdict!r})"],
    }


def researcher(state: TeamState) -> TeamState:
    """Поисковик работает только с каталогом и не додумывает курсы от себя."""
    catalog = "\n".join(f"{c['code']}: {c['title']} — {c['about']}" for c in CATALOG)
    out = ask(
        "Ты поисковый агент. Выбери из каталога 1-2 подходящих курса. "
        "Отвечай строками вида КОД: причина. Курсы вне каталога называть запрещено.",
        f"Каталог:\n{catalog}\n\nЗапрос: {state['request']}",
    )
    return {"findings": out, "route_log": ["researcher: отработал"]}


def analyst(state: TeamState) -> TeamState:
    """Аналитик превращает находки в рекомендацию для человека."""
    out = ask(
        "Ты агент-аналитик. По находкам коллеги дай рекомендацию строго одним абзацем "
        "из 2-3 предложений на русском языке. Новых курсов не добавляй, запрос не повторяй, "
        "диалог не продолжай.",
        f"Запрос: {state['request']}\nНаходки:\n{state['findings']}",
    )
    return {"analysis": out, "route_log": ["analyst: отработал"]}


def critic(state: TeamState) -> TeamState:
    """Критик сверяет рекомендацию с каталогом, это дешёвая защита от выдумок."""
    codes = ", ".join(c["code"] for c in CATALOG)
    out = ask(
        "Ты агент-контролёр. Разрешённые коды курсов: "
        f"{codes}. Проверь, что в рекомендации нет других кодов. Первым словом ответь ОК или ОШИБКА, "
        "дальше одна строка пояснения.",
        f"Рекомендация:\n{state['analysis']}",
    )
    return {"review": out, "route_log": ["critic: отработал"]}


def route(state: TeamState) -> str:
    """Переход по решению супервизора плюс жёсткий лимит шагов."""
    if state["steps"] > 8:
        return END
    return state.get("next", END)


graph = StateGraph(TeamState)
graph.add_node("supervisor", supervisor)
graph.add_node("researcher", researcher)
graph.add_node("analyst", analyst)
graph.add_node("critic", critic)
graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route, {"researcher": "researcher", "analyst": "analyst", "critic": "critic", "FINISH": END, END: END})
for worker in ("researcher", "analyst", "critic"):
    graph.add_edge(worker, "supervisor")
app = graph.compile()

if __name__ == "__main__":
    task = "Я инженер данных, работаю с батчами, хочу перейти в потоковую обработку. Что учить?"
    result = app.invoke({"request": task, "findings": "", "analysis": "", "review": "", "route_log": [], "steps": 0, "next": ""})
    print("=== Маршрут ===")
    for line in result["route_log"]:
        print(line)
    print("\n=== Находки поисковика ===\n" + result["findings"])
    print("\n=== Рекомендация аналитика ===\n" + result["analysis"])
    print("\n=== Вердикт критика ===\n" + result["review"])
