# RUNBOOK. OpenRouter за 15 минут: ключ, первый запрос, оплата из России

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, openai 2.53.0, httpx 0.28.1, curl 8.5.0. Ключ лежит в переменной окружения `OPENROUTER_API_KEY`, в код и в вывод не вписывается. Файлы кода: `first_request.py`, `check_credits.py`.

## Шаг 1. Ключ в переменной окружения

```bash
export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"
```

Проверка: `echo $OPENROUTER_API_KEY` печатает строку, начинающуюся на `sk-or-v1-`. Шаг пройден, если строка не пустая.

## Шаг 2. Смоук-тест через curl

```bash
curl -s https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"Скажи одним словом: работает?"}]}'
```

Ожидаемый вывод (реальный прогон, сокращён до сути):

```
{"model":"openai/gpt-4o-mini","provider":"OpenAI",
 "choices":[{"message":{"role":"assistant","content":"Да."}}],
 "usage":{"prompt_tokens":16,"completion_tokens":2,"total_tokens":18,"cost":0.0000036}}
```

Шаг пройден, если в ответе есть поле `choices` с текстом, а не ошибка авторизации.

## Шаг 3. Первый запрос через Python (first_request.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[
        {"role": "user", "content": "Поздоровайся одной короткой фразой и подтверди, что доступ к модели работает."}
    ],
)

print("Ответ модели:")
print(resp.choices[0].message.content)
print("---")
print("model:", resp.model)
print("prompt_tokens:", resp.usage.prompt_tokens)
print("completion_tokens:", resp.usage.completion_tokens)
print("total_tokens:", resp.usage.total_tokens)
```

Команда: `python3 first_request.py`

Ожидаемый вывод (реальный прогон):

```
Ответ модели:
Привет! Доступ к модели работает.
---
model: openai/gpt-4o-mini
prompt_tokens: 28
completion_tokens: 9
total_tokens: 37
```

Шаг пройден, если печатается связный ответ модели и три счётчика токенов больше нуля. Точный текст ответа может немного отличаться от запуска к запуску, это нормально, модель не детерминирована.

## Шаг 4. Баланс и расход через curl

```bash
curl -s https://openrouter.ai/api/v1/credits \
  -H "Authorization: Bearer $OPENROUTER_API_KEY"
```

Ожидаемый вывод: `{"data":{"total_credits":10,"total_usage":0.0000354}}`. Шаг пройден, если `total_credits` больше нуля.

## Шаг 5. Баланс через Python (check_credits.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]

r = httpx.get(
    "https://openrouter.ai/api/v1/credits",
    headers={"Authorization": f"Bearer {key}"},
    timeout=15,
)
r.raise_for_status()

data = r.json()["data"]
total = data["total_credits"]
used = data["total_usage"]

print(f"total_credits: {total:.4f}")
print(f"total_usage: {used:.6f}")
print(f"remaining: {total - used:.6f}")
```

Команда: `python3 check_credits.py`

Ожидаемый вывод (реальный прогон):

```
total_credits: 10.0000
total_usage: 0.000035
remaining: 9.999965
```

Шаг пройден, если `remaining` положительный и близок к `total_credits`.

## Шаг 6. Расход по ключу через curl

```bash
curl -s https://openrouter.ai/api/v1/auth/key \
  -H "Authorization: Bearer $OPENROUTER_API_KEY"
```

Ожидаемый вывод (поля сокращены):

```
{"data":{"label":"sk-or-v1-e2e...c48","limit":null,"limit_remaining":null,
 "usage":0.000045,"usage_daily":0.0000096,
 "usage_weekly":0.000045,"usage_monthly":0.000045,"is_free_tier":false}}
```

Шаг пройден, если приходит JSON с полем `usage`, а не 401.

## Что делать если не так

- Код 401 на любом шаге: ключ не подставился в заголовок или указан с опечаткой. Проверьте `echo $OPENROUTER_API_KEY`.
- Код 403 или пустой ответ: похоже на гео-блокировку Cloudflare для российского IP. Нужен EU или другой разрешённый регион, прокси или зарубежный сервер.
- `total_credits: 0`: баланс не пополнен. Из России рабочий путь пополнения это оплата криптовалютой USDC, картой РФ обычно не проходит.
- `ModuleNotFoundError: No module named 'openai'` или `'httpx'`: не установлены зависимости, `pip install openai httpx --break-system-packages`.
