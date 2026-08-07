# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Первый запрос к модели через OpenRouter одним OpenAI-совместимым клиентом.
import os
from openai import OpenAI

# Клиент OpenAI, но base_url указывает на OpenRouter. Ключ из окружения, в код не вписываем.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# Обычный chat-запрос. Модель задаём строкой в формате провайдер/название.
resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[
        {"role": "user", "content": "Поздоровайся одной короткой фразой и подтверди, что доступ к модели работает."}
    ],
)

# Печатаем ответ модели и счётчики токенов из блока usage.
print("Ответ модели:")
print(resp.choices[0].message.content)
print("---")
print("model:", resp.model)
print("prompt_tokens:", resp.usage.prompt_tokens)
print("completion_tokens:", resp.usage.completion_tokens)
print("total_tokens:", resp.usage.total_tokens)
