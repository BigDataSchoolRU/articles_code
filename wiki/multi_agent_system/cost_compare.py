# LangGraph 1.2.11, langchain-ollama 1.1.0, Python 3.12.13, Ollama 0.32.9, модель qwen2.5:7b. Прогнано на стенде.
"""Цена координации: одна и та же задача одним агентом и командой из трёх агентов.

Скрипт считает токены и время по метаданным ответов Ollama, чтобы разница между
двумя подходами была не рассуждением, а числом.
"""

import time

from langchain_ollama import ChatOllama

MODEL = "qwen2.5:7b"
llm = ChatOllama(model=MODEL, temperature=0)

CATALOG = """DEVKI: Apache Kafka для инженеров данных — потоковая передача, топики, продюсеры и консьюмеры
FLINK: Потоковая обработка данных с Apache Flink — стриминговые джобы, окна, состояние
AIRF: Apache Airflow для инженеров данных — пакетные пайплайны, DAG, расписания
AGENT: ИИ-агенты для оптимизации бизнес-процессов — LLM-агенты, инструменты, мультиагентные системы"""

TASK = "Я инженер данных, работаю с батчами, хочу перейти в потоковую обработку. Что учить?"


def call(system: str, user: str) -> tuple[str, int]:
    """Возвращает текст ответа и суммарное число токенов промпта и генерации."""
    msg = llm.invoke([("system", system), ("human", user)])
    meta = msg.response_metadata
    tokens = meta.get("prompt_eval_count", 0) + meta.get("eval_count", 0)
    return msg.content.strip(), tokens


def single_agent() -> tuple[str, int]:
    """Один агент делает всю работу за один вызов модели."""
    return call(
        "Ты консультант по обучению. Подбери курс из каталога, обоснуй выбор, "
        "проверь себя. Отвечай только на русском.",
        f"Каталог:\n{CATALOG}\n\nЗапрос: {TASK}",
    )


def multi_agent() -> tuple[str, int]:
    """Три агента по очереди: поиск, рекомендация, проверка. Три вызова модели."""
    total = 0
    found, t = call("Ты поисковый агент. Выбери 1-2 курса из каталога, отвечай строками КОД: причина.",
                    f"Каталог:\n{CATALOG}\n\nЗапрос: {TASK}")
    total += t
    advice, t = call("Ты агент-аналитик. Дай рекомендацию строго одним абзацем из 2-3 предложений на русском языке. Запрос не повторяй, диалог не продолжай.",
                     f"Запрос: {TASK}\nНаходки:\n{found}")
    total += t
    review, t = call("Ты агент-контролёр. Проверь, что упомянуты только коды DEVKI, FLINK, AIRF, AGENT. Ответь ОК или ОШИБКА и причину.",
                     f"Рекомендация:\n{advice}")
    total += t
    return f"{advice}\n[контроль] {review}", total


if __name__ == "__main__":
    for name, fn in (("Один агент", single_agent), ("Команда из трёх агентов", multi_agent)):
        start = time.monotonic()
        answer, tokens = fn()
        elapsed = time.monotonic() - start
        print(f"=== {name} ===")
        print(f"токенов: {tokens}, время: {elapsed:.1f} с")
        print(answer)
        print()
