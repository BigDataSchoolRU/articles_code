# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Auto-роутер: особый идентификатор openrouter/auto, роутер сам подбирает модель под запрос.
import os
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# Модель не выбираем вручную, отдаём выбор роутеру через openrouter/auto.
resp = client.chat.completions.create(
    model="openrouter/auto",
    messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
    max_tokens=20,
)

# resp.model покажет, какую модель роутер выбрал на самом деле.
print("реально ответила модель:", resp.model, "| провайдер:", resp.provider)
