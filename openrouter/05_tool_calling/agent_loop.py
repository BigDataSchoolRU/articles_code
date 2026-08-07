# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Многошаговый агентный цикл: модель вызывает инструменты по кругу, пока не соберёт ответ.
import os, json
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

def get_user_city():
    return "Москва"

def get_weather(city):
    return {"Москва": "+18, ясно"}.get(city, "нет данных")

# Диспетчер: имя инструмента -> реальная функция.
funcs = {
    "get_user_city": lambda a: get_user_city(),
    "get_weather": lambda a: get_weather(a["city"]),
}

# Два зависимых инструмента: сначала узнать город, потом погоду в нём.
tools = [
    {"type": "function", "function": {"name": "get_user_city",
        "description": "Город текущего пользователя", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_weather",
        "description": "Погода в указанном городе",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
]

messages = [{"role": "user", "content": "Какая погода у меня? Сначала узнай мой город, потом погоду. Ответь одной фразой."}]

step = 0
while True:
    step += 1
    # Запрос к модели с историей и списком инструментов.
    resp = client.chat.completions.create(model="openai/gpt-4o-mini", messages=messages, tools=tools)
    msg = resp.choices[0].message
    messages.append(msg.model_dump())
    # Нет вызовов инструментов, значит модель дала финальный ответ, выходим.
    if not msg.tool_calls:
        print("шаг", step, "финал:", msg.content)
        break
    # Иначе исполняем каждый вызов и возвращаем результат модели.
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments or "{}")
        result = funcs[tc.function.name](args)
        print("шаг", step, "вызов", tc.function.name, args, "->", result)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
