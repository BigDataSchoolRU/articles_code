# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Контроль расхода: лимит и трата ключа через /auth/key плюс баланс через /credits.
import os
import httpx

# Ключ из окружения, общий заголовок авторизации.
key = os.environ["OPENROUTER_API_KEY"]
headers = {"Authorization": f"Bearer {key}"}

# /auth/key отдаёт лимит ключа и расход в разрезах день/неделя/месяц.
k = httpx.get("https://openrouter.ai/api/v1/auth/key", headers=headers, timeout=15).json()["data"]
# /credits отдаёт общий баланс и суммарную трату аккаунта.
c = httpx.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=15).json()["data"]

# limit=None означает, что жёсткого потолка на ключе нет, расход упирается в баланс.
print("лимит ключа:      ", k["limit"])
print("остаток лимита:   ", k["limit_remaining"])
print(f"расход за день:    {k['usage_daily']:.6f}")
print(f"расход за месяц:   {k['usage_monthly']:.6f}")
print(f"баланс аккаунта:   {c['total_credits']:.4f}, потрачено {c['total_usage']:.6f}")
