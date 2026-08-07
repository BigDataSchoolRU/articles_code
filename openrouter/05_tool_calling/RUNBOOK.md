# RUNBOOK. Tool calling, структурированный вывод и агенты

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, openai 2.53.0. Ключ в `OPENROUTER_API_KEY`. Файлы кода: `tool_calling.py`, `agent_loop.py`, `structured_output.py`, `response_healing.py`.

## Шаг 1. Базовый tool calling (tool_calling.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os, json
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

def get_weather(city):
    data = {"Москва": "+18, ясно", "Берлин": "+15, дождь"}
    return data.get(city, "нет данных")

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Погода в указанном городе",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]

messages = [{"role": "user", "content": "Какая погода в Москве и Берлине? Ответь одной фразой."}]

first = client.chat.completions.create(model="openai/gpt-4o-mini", messages=messages, tools=tools)
call = first.choices[0].message
messages.append(call.model_dump())
print("запрошено вызовов:", len(call.tool_calls or []))

for tc in call.tool_calls or []:
    args = json.loads(tc.function.arguments)
    result = get_weather(args["city"])
    print("  вызов", tc.function.name, args, "->", result)
    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

final = client.chat.completions.create(model="openai/gpt-4o-mini", messages=messages, tools=tools)
print("финал:", final.choices[0].message.content)
```

Команда: `python3 tool_calling.py`

Ожидаемый вывод (реальный прогон):

```
запрошено вызовов: 2
  вызов get_weather {'city': 'Москва'} -> +18, ясно
  вызов get_weather {'city': 'Берлин'} -> +15, дождь
финал: В Москве +18 градусов и ясно, в Берлине +15 градусов и дождь.
```

Шаг пройден, если модель запросила ровно 2 вызова функции (по городу на каждый) и финальный ответ упоминает оба города с верными данными. Точная формулировка финальной фразы может отличаться.

## Шаг 2. Многошаговый агентный цикл (agent_loop.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os, json
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

def get_user_city():
    return "Москва"

def get_weather(city):
    return {"Москва": "+18, ясно"}.get(city, "нет данных")

funcs = {
    "get_user_city": lambda a: get_user_city(),
    "get_weather": lambda a: get_weather(a["city"]),
}

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
    resp = client.chat.completions.create(model="openai/gpt-4o-mini", messages=messages, tools=tools)
    msg = resp.choices[0].message
    messages.append(msg.model_dump())
    if not msg.tool_calls:
        print("шаг", step, "финал:", msg.content)
        break
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments or "{}")
        result = funcs[tc.function.name](args)
        print("шаг", step, "вызов", tc.function.name, args, "->", result)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
```

Команда: `python3 agent_loop.py`

Ожидаемый вывод (реальный прогон):

```
шаг 1 вызов get_user_city {} -> Москва
шаг 2 вызов get_weather {'city': 'Москва'} -> +18, ясно
шаг 3 финал: В Москве сейчас +18°C и ясно.
```

Шаг пройден, если цикл прошёл ровно три шага в этом порядке: сначала город, потом погода, потом финальный ответ без вызовов. Если модель объединит два вызова в один шаг, это тоже корректное поведение агента, просто короче.

## Шаг 3. Структурированный вывод по JSON-схеме (structured_output.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os, json
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

schema = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "temp_c": {"type": "integer"},
        "condition": {"type": "string"},
    },
    "required": ["city", "temp_c", "condition"],
    "additionalProperties": False,
}

resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Извлеки данные: В Москве плюс 18 и ясно."}],
    response_format={"type": "json_schema", "json_schema": {"name": "weather", "strict": True, "schema": schema}},
)

raw = resp.choices[0].message.content
print("сырой ответ:", raw)

data = json.loads(raw)
print("город:", data["city"], "| темп:", data["temp_c"], "| небо:", data["condition"])
```

Команда: `python3 structured_output.py`

Ожидаемый вывод (реальный прогон):

```
сырой ответ: {"city":"Москва","temp_c":18,"condition":"ясно"}
город: Москва | темп: 18 | небо: ясно
```

Шаг пройден, если `json.loads(raw)` не падает и в ответе присутствуют ровно три поля схемы: `city`, `temp_c`, `condition`.

## Шаг 4. Response Healing (response_healing.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os, json
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Верни JSON объект с полями name и ok"}],
    response_format={"type": "json_object"},
    extra_body={"plugins": [{"id": "response-healing"}]},
)

raw = resp.choices[0].message.content
print("ответ:", raw)

data = json.loads(raw)
print("распарсено без ошибок, ключи:", list(data.keys()))
```

Команда: `python3 response_healing.py`

Ожидаемый вывод (реальный прогон):

```
распарсено без ошибок, ключи: ['name', 'ok']
```

Шаг пройден, если `json.loads` не падает и в ключах присутствуют `name` и `ok`. Плагин чинит синтаксис JSON, а не структуру, поэтому если хотите увидеть его в работе нагляднее, попробуйте более длинный или сложный запрошенный объект, где модели легче потерять запятую или скобку.

## Что делать если не так

- `tool_calling.py` или `agent_loop.py`: модель не запросила вызов инструмента вовсе - переформулируйте system/user так, чтобы явно требовался внешний факт, некоторые модели предпочитают отвечать из своих знаний.
- `structured_output.py`: ошибка от API про неподдерживаемый `response_format` - не у всех моделей есть строгий json_schema, для проверки используйте модели с явной поддержкой (в том числе openai/gpt-4o-mini).
- `response_healing.py`: `json.loads` всё равно падает - снимите плагин и посмотрите на сырой ответ, возможно проблема не в синтаксисе JSON, а в том, что модель вернула текст вместо объекта.
- `KeyError` при разборе `tc.function.arguments`: аргументы пришли пустой строкой, добавьте `or "{}"` перед `json.loads`, как это уже сделано в `agent_loop.py`.
