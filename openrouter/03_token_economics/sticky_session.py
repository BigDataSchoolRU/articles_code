# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Липкая маршрутизация: session_id держит запросы у одного провайдера ради тёплого кэша.
import os
import httpx

# Ключ из окружения, модель с несколькими провайдерами.
key = os.environ["OPENROUTER_API_KEY"]
MODEL = "meta-llama/llama-3.3-70b-instruct"

def call(extra):
    # Базовый запрос плюс дополнительные поля (session_id или provider).
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "ок"}], "max_tokens": 5}
    payload.update(extra)
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    # Возвращаем имя провайдера, который обслужил запрос.
    return r.json()["provider"]

# С фиксированным session_id запросы липнут к одному провайдеру.
pinned = [call({"session_id": "orders-bot-42"}) for _ in range(6)]
# По умолчанию роутер балансирует нагрузку между провайдерами.
default = [call({}) for _ in range(6)]

# Сравниваем число уникальных провайдеров в каждом случае.
print("session_id:", pinned, "->", len(set(pinned)), "провайдер")
print("default:   ", default, "->", len(set(default)), "провайдера")
