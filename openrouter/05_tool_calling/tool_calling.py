# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Tool calling: модель сама просит вызвать функцию, мы исполняем и возвращаем результат.
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

# Первый вызов: модель решает, какие инструменты дёрнуть.
first = client.chat.completions.create(model="openai/gpt-4o-mini", messages=messages, tools=tools)
call = first.choices[0].message
messages.append(call.model_dump())
print("запрошено вызовов:", len(call.tool_calls or []))

# Исполняем каждый вызов и возвращаем результат модели.
for tc in call.tool_calls or []:
    args = json.loads(tc.function.arguments)
    result = get_weather(args["city"])
    print("  вызов", tc.function.name, args, "->", result)
    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

# Второй вызов: модель собирает финальный ответ из результатов.
final = client.chat.completions.create(model="openai/gpt-4o-mini", messages=messages, tools=tools)
print("финал:", final.choices[0].message.content)
