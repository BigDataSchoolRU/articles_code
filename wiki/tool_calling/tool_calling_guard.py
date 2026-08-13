# Прогон: ollama-python 0.6.2, Ollama 0.32.9, модель qwen2.5:7b, pydantic 2.13.4, Python 3.12.13
"""Две проверки вокруг Tool Calling: валидация вызова и цена каталога инструментов в токенах."""

import copy
from pydantic import BaseModel, ValidationError
from ollama import Client

from tool_calling_demo import MODEL, TOOLS, REGISTRY

client = Client(host="http://localhost:11434")


class CourseInfoArgs(BaseModel):
    """Контракт аргументов инструмента, модель его не гарантирует."""

    code: str


class DiscountArgs(BaseModel):
    price: int
    percent: int


SCHEMAS = {"get_course_info": CourseInfoArgs, "calc_discount": DiscountArgs}


def safe_dispatch(name: str, args: dict) -> str:
    """Диспетчер, который сначала проверяет имя и аргументы, и только потом вызывает функцию."""
    if name not in REGISTRY:
        return f"отказ: инструмент {name} не объявлен"
    try:
        checked = SCHEMAS[name](**args)
    except ValidationError as err:
        return f"отказ: аргументы не прошли валидацию, {err.error_count()} ошибка(и)"
    return REGISTRY[name](**checked.model_dump())


def measure(n_tools: int) -> int:
    """Замер служебных токенов: сколько стоит сам факт объявления инструментов."""
    tools = None
    if n_tools:
        tools = []
        for i in range(n_tools):
            tool = copy.deepcopy(TOOLS[i % len(TOOLS)])
            tool["function"]["name"] = f"{tool['function']['name']}_{i}"
            tools.append(tool)
    reply = client.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "Привет"}],
        tools=tools,
        options={"num_predict": 1},
    )
    return reply.prompt_eval_count


if __name__ == "__main__":
    print("=== Валидация вызовов, аргументы подставлены вручную ===")
    cases = [
        ("get_course_info", {"code": "AGENT"}),
        ("get_weather", {"city": "Москва"}),
        ("calc_discount", {"price": "девяносто тысяч", "percent": 15}),
    ]
    for name, args in cases:
        print(f"{name}({args}) -> {safe_dispatch(name, args)}")

    print("\n=== Цена каталога инструментов в токенах промпта ===")
    for n in (0, 2, 10):
        print(f"инструментов {n}: prompt_eval_count = {measure(n)}")
