# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Контроль по ключу: лимит, признак free-tier и расход в разрезах через /auth/key.
import os
import httpx

# Ключ из окружения.
key = os.environ["OPENROUTER_API_KEY"]

# /auth/key отдаёт метаданные конкретного ключа: лимит, тариф и расход.
d = httpx.get(
    "https://openrouter.ai/api/v1/auth/key",
    headers={"Authorization": f"Bearer {key}"},
    timeout=15,
).json()["data"]

# limit=None означает, что жёсткого потолка нет и расход упирается только в баланс.
print("limit:", d["limit"])
print("is_free_tier:", d["is_free_tier"])
print(f"usage: {d['usage']:.5f}")
print(f"usage_daily: {d['usage_daily']:.6f}")
