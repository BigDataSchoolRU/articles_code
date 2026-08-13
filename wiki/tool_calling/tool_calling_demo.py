# Прогон: ollama-python 0.6.2, Ollama 0.32.9, модель qwen2.5:7b, Python 3.12.13
"""Tool Calling на локальной модели: объявление инструментов, диспетчер и агентный цикл."""

import json
from ollama import Client

MODEL = "qwen2.5:7b"
client = Client(host="http://localhost:11434")

# Мини-справочник курсов, роль внешнего источника данных
COURSES = {
    "AGENT": {"name": "ИИ-агенты для оптимизации бизнес-процессов", "hours": 24, "price": 90000},
    "MLOPS": {"name": "Разработка и внедрение ML-решений", "hours": 24, "price": 90000},
    "KAFKA": {"name": "Apache Kafka: администрирование кластера", "hours": 24, "price": 96000},
}


def get_course_info(code: str) -> str:
    """Инструмент 1: отдаёт карточку курса по коду."""
    course = COURSES.get(code.upper())
    if course is None:
        return json.dumps({"error": f"курс {code} не найден"}, ensure_ascii=False)
    return json.dumps(course, ensure_ascii=False)


def calc_discount(price: int, percent: int) -> str:
    """Инструмент 2: считает цену со скидкой, арифметика вынесена из модели."""
    return json.dumps({"final_price": round(price * (100 - percent) / 100)}, ensure_ascii=False)


# Объявление инструментов: имя, описание и JSON Schema параметров.
# Именно этот блок модель видит вместе с запросом и по нему принимает решение.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_course_info",
            "description": "Вернуть название, длительность и цену курса по его коду",
            "parameters": {
                "type": "object",
                "required": ["code"],
                "properties": {
                    "code": {"type": "string", "description": "Код курса, например AGENT"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc_discount",
            "description": "Посчитать итоговую цену после скидки в процентах",
            "parameters": {
                "type": "object",
                "required": ["price", "percent"],
                "properties": {
                    "price": {"type": "integer", "description": "Цена без скидки в рублях"},
                    "percent": {"type": "integer", "description": "Размер скидки в процентах"},
                },
            },
        },
    },
]

REGISTRY = {"get_course_info": get_course_info, "calc_discount": calc_discount}


def run(question: str, max_steps: int = 5) -> None:
    """Агентный цикл: модель зовёт инструменты, пока не соберёт ответ."""
    messages = [{"role": "user", "content": question}]
    for step in range(1, max_steps + 1):
        reply = client.chat(model=MODEL, messages=messages, tools=TOOLS)
        messages.append(reply.message)
        calls = reply.message.tool_calls or []
        if not calls:
            # Инструменты не нужны, модель отвечает текстом и цикл закрывается
            print(f"[шаг {step}] ответ модели: {reply.message.content.strip()}")
            return
        for call in calls:
            name = call.function.name
            args = call.function.arguments
            print(f"[шаг {step}] модель вызвала {name} с аргументами {dict(args)}")
            fn = REGISTRY.get(name)
            # Имя инструмента приходит строкой, поэтому реестр проверяется до вызова
            result = fn(**args) if fn else json.dumps({"error": "неизвестный инструмент"})
            print(f"[шаг {step}] результат инструмента: {result}")
            messages.append({"role": "tool", "tool_name": name, "content": result})
    print("[стоп] превышен лимит шагов, цикл остановлен предохранителем")


if __name__ == "__main__":
    print("=== Сценарий 1: нужны оба инструмента ===")
    run("Сколько стоит курс AGENT со скидкой 15 процентов? Ответь одной фразой.")
    print("\n=== Сценарий 2: инструменты не нужны ===")
    run("Что означает аббревиатура API? Ответь одним предложением.")
