# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Резерв по моделям: если первую обслужить некому, запрос уходит на вторую.
import os
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# Список моделей: основная плюс резервная.
FALLBACK = ["meta-llama/llama-3.3-70b-instruct", "openai/gpt-4o-mini"]
messages = [{"role": "user", "content": "Ответь одним словом: готово"}]

# Обычный вызов: первую модель есть кому обслужить, отвечает она.
normal = client.chat.completions.create(
    model=FALLBACK[0],
    messages=messages,
    max_tokens=20,
    extra_body={"models": FALLBACK},
)
print("обычный вызов -> ответила:", normal.model, "| провайдер:", normal.provider)

# Ломаем первую: разрешаем только провайдера OpenAI, который llama не обслуживает.
# OpenRouter видит, что первую подать некому, и переключается на вторую из списка.
forced = client.chat.completions.create(
    model=FALLBACK[0],
    messages=messages,
    max_tokens=20,
    extra_body={"models": FALLBACK, "provider": {"only": ["OpenAI"]}},
)
print("сбой первой   -> ответила:", forced.model, "| провайдер:", forced.provider)
