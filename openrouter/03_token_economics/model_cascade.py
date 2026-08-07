# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Каскад: простые задачи идут на дешёвую модель, сложные эскалируются на сильную.
import os
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

CHEAP = "openai/gpt-4o-mini"   # дешёвая модель для простого
STRONG = "openai/gpt-4o"       # сильная модель для сложного

def is_hard(prompt):
    # Грубая эвристика сложности: длинный запрос или аналитические слова-маркеры.
    markers = ("докажи", "проанализируй", "спроектируй", "выведи формулу")
    return len(prompt) > 200 or any(m in prompt.lower() for m in markers)

def route(prompt):
    # Выбираем модель по сложности и делаем запрос.
    model = STRONG if is_hard(prompt) else CHEAP
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        extra_body={"usage": {"include": True}},  # просим вернуть стоимость
    )
    # Стоимость лежит в usage.cost (в SDK это доп. поле, берём с запасным путём).
    cost = getattr(resp.usage, "cost", None)
    if cost is None:
        cost = (resp.usage.model_extra or {}).get("cost")
    return model, cost

# Два запроса: простой и аналитический.
tasks = [
    "Переведи слово cat на русский",
    "Проанализируй риски миграции монолита на микросервисы и предложи план",
]
for t in tasks:
    model, cost = route(t)
    print(f"{model:<20} cost=${cost:.6f}  <- {t[:40]}")
