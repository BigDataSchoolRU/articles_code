# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Приватность через маршрутизацию: пускаем запрос только через провайдеров без хранения данных.
import os
import httpx

# Ключ из окружения, общий заголовок.
key = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {key}"}
MODEL = "meta-llama/llama-3.3-70b-instruct"

def who(extra):
    # Один и тот же запрос, разные настройки провайдера. Возвращаем, кто обслужил.
    p = {"model": MODEL, "messages": [{"role": "user", "content": "ок"}], "max_tokens": 5}
    p.update(extra)
    return httpx.post("https://openrouter.ai/api/v1/chat/completions", headers=H, json=p, timeout=60).json()["provider"]

# data_collection="deny": исключаем провайдеров, которые сохраняют промпты.
print("data_collection=deny ->", who({"provider": {"data_collection": "deny"}}))
# Без ограничения политики данных провайдером может стать кто угодно.
print("без ограничения     ->", who({"provider": {"sort": "throughput"}}))
