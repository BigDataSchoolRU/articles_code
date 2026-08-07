# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Структурированный вывод: модель обязана ответить строго по JSON-схеме.
import os, json
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# Схема ответа: какие поля и типы обязательны, лишние запрещены.
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

# strict=True включает жёсткую проверку схемы на стороне провайдера.
resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Извлеки данные: В Москве плюс 18 и ясно."}],
    response_format={"type": "json_schema", "json_schema": {"name": "weather", "strict": True, "schema": schema}},
)

raw = resp.choices[0].message.content
print("сырой ответ:", raw)

# Ответ гарантированно валидный JSON нужной формы, парсим без страха.
data = json.loads(raw)
print("город:", data["city"], "| темп:", data["temp_c"], "| небо:", data["condition"])
