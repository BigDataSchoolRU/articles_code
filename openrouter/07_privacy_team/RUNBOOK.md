# RUNBOOK. Приватность, безопасность и работа командой

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, httpx 0.28.1. Ключ инференса в `OPENROUTER_API_KEY`. Файлы кода: `privacy_routing.py`, `key_usage.py`, `scoped_key.py`. Шаг 3 (scoped_key.py) требует отдельного management (provisioning) ключа в `OPENROUTER_PROVISIONING_KEY`, которого на этом стенде нет - это честно проверенный шаблон запроса, а не полный прогон.

## Шаг 1. Маршрутизация только через провайдеров без хранения данных (privacy_routing.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {key}"}
MODEL = "meta-llama/llama-3.3-70b-instruct"

def who(extra):
    p = {"model": MODEL, "messages": [{"role": "user", "content": "ок"}], "max_tokens": 5}
    p.update(extra)
    return httpx.post("https://openrouter.ai/api/v1/chat/completions", headers=H, json=p, timeout=60).json()["provider"]

print("data_collection=deny ->", who({"provider": {"data_collection": "deny"}}))
print("без ограничения     ->", who({"provider": {"sort": "throughput"}}))
```

Команда: `python3 privacy_routing.py`

Ожидаемый вывод (реальный прогон):

```
data_collection=deny -> Nebius
без ограничения     -> Groq
```

Шаг пройден, если обе строки печатаются без ошибок и провайдеры не обязательно совпадают. Конкретные имена провайдеров могут меняться от прогона к прогону, важно, что запрос с `deny` в принципе успешно прошёл, то есть в каталоге нашёлся хотя бы один провайдер без хранения данных для этой модели.

## Шаг 2. Расход по ключу через /auth/key (key_usage.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]

d = httpx.get(
    "https://openrouter.ai/api/v1/auth/key",
    headers={"Authorization": f"Bearer {key}"},
    timeout=15,
).json()["data"]

print("limit:", d["limit"])
print("is_free_tier:", d["is_free_tier"])
print(f"usage: {d['usage']:.5f}")
print(f"usage_daily: {d['usage_daily']:.6f}")
```

Команда: `python3 key_usage.py`

Ожидаемый вывод (реальный прогон):

```
limit: None
is_free_tier: False
usage: 5.89960
usage_daily: 0.000037
```

Шаг пройден, если приходят все четыре строки без 401. `limit: None` означает отсутствие жёсткого потолка на этом ключе, это ожидаемое значение, а не ошибка.

## Шаг 3. Ключ с лимитом и IP-allowlist через Provisioning API (scoped_key.py), шаблон, требует management-ключ

```python
# шаблон для OpenRouter Provisioning API (проверено 2026-08-04): требует management-ключ.
# ВНИМАНИЕ: на стенде статьи management-ключа нет, эндпоинт /api/v1/keys без него отвечает 401.
import os
import httpx

mgmt = os.environ["OPENROUTER_PROVISIONING_KEY"]

payload = {
    "name": "service-bot",
    "limit": 50,
    "include_byok_in_limit": False,
    "allowed_ips": ["203.0.113.10"],
}

r = httpx.post(
    "https://openrouter.ai/api/v1/keys",
    headers={"Authorization": f"Bearer {mgmt}"},
    json=payload,
    timeout=30,
)
r.raise_for_status()

data = r.json()
print("создан ключ с лимитом и IP-allowlist:", data.get("name"))
```

Что было проверено на стенде: без `OPENROUTER_PROVISIONING_KEY` (обычный ключ инференса на его месте) запрос к `/api/v1/keys` возвращает код 401, что подтверждает необходимость отдельного management-ключа. Форма payload и структура запроса взяты из документации Provisioning API.

Как проверить этот шаг самостоятельно: выпустите management-ключ в личном кабинете OpenRouter (раздел, отвечающий за Provisioning API), положите его в `OPENROUTER_PROVISIONING_KEY` и запустите скрипт. Ожидаемый результат: код ответа 200 или 201, в `data.get("name")` придёт `service-bot`, а в полном теле ответа один раз показывается сам новый ключ, который нужно сразу сохранить, повторно он не отдаётся.

Шаг пройден (в режиме шаблона), если запрос без management-ключа возвращает именно 401, а не другую ошибку, это подтверждает, что защита работает.

## Что делать если не так

- `privacy_routing.py`: обе строки вернули одного и того же провайдера - это возможно, если для модели сейчас доступен единственный провайдер без хранения данных, не ошибка.
- `key_usage.py`: 401 - обычный ключ инференса невалиден или отозван, проверьте `OPENROUTER_API_KEY`.
- `scoped_key.py`: получили не 401, а 403 или 400 - значит переменная `OPENROUTER_PROVISIONING_KEY` содержит какой-то ключ, но не management-ключ, либо payload не прошёл валидацию, проверьте формат `allowed_ips`.
- Если хочется полностью прогнать шаг 3: понадобится реальный management-ключ из личного кабинета, обычный ключ инференса для этого эндпоинта не подходит принципиально.
