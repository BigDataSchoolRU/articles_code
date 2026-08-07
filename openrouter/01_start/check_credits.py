# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Проверка баланса и расхода по ключу через эндпоинт /credits.
import os
import httpx

# Ключ из окружения.
key = os.environ["OPENROUTER_API_KEY"]

# GET на /credits: эндпоинт отдаёт купленные кредиты и суммарный расход.
r = httpx.get(
    "https://openrouter.ai/api/v1/credits",
    headers={"Authorization": f"Bearer {key}"},
    timeout=15,
)
r.raise_for_status()  # упадём с понятной ошибкой, если ключ не принят

# Остаток считаем как разницу баланса и расхода.
data = r.json()["data"]
total = data["total_credits"]
used = data["total_usage"]

print(f"total_credits: {total:.4f}")
print(f"total_usage: {used:.6f}")
print(f"remaining: {total - used:.6f}")
