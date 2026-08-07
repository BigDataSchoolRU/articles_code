# шаблон для OpenRouter Provisioning API (проверено 2026-08-04): требует management-ключ.
# ВНИМАНИЕ: на стенде статьи management-ключа нет, эндпоинт /api/v1/keys без него отвечает 401.
# Скрипт показывает форму запроса на выпуск scoped-ключа с лимитом и IP-allowlist.
import os
import httpx

# Здесь нужен именно management (provisioning) ключ, а не обычный ключ инференса.
mgmt = os.environ["OPENROUTER_PROVISIONING_KEY"]

# Выпускаем ключ с ограничениями: имя, потолок расхода и белый список IP.
payload = {
    "name": "service-bot",          # понятное имя ключа
    "limit": 50,                    # потолок расхода в долларах
    "include_byok_in_limit": False, # BYOK-трафик не учитывать в лимите
    "allowed_ips": ["203.0.113.10"],  # запросы только с этих адресов
}

r = httpx.post(
    "https://openrouter.ai/api/v1/keys",
    headers={"Authorization": f"Bearer {mgmt}"},
    json=payload,
    timeout=30,
)
r.raise_for_status()

# В ответе приходит сам ключ (показывается один раз) и его параметры.
data = r.json()
print("создан ключ с лимитом и IP-allowlist:", data.get("name"))
