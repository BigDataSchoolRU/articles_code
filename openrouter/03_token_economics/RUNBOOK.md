# RUNBOOK. Экономика токенов: кэш, sticky-роутинг, каскад, субагенты

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, openai 2.53.0, httpx 0.28.1. Ключ в `OPENROUTER_API_KEY`. Файлы кода: `prompt_cache.py`, `sticky_session.py`, `model_cascade.py`, `subagent_demo.py`, `spend_limit.py`.

## Шаг 1. Кэш промптов (prompt_cache.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]
context = "Справочный контекст для кэша. " * 900

def ask():
    payload = {
        "model": "anthropic/claude-haiku-4.5",
        "messages": [
            {"role": "system", "content": [
                {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}}
            ]},
            {"role": "user", "content": "Ответь одним словом: ок"},
        ],
        "max_tokens": 5,
        "session_id": "cache-demo-1",
        "usage": {"include": True},
    }
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    u = r.json()["usage"]
    cached = u["prompt_tokens_details"]["cached_tokens"]
    return u["prompt_tokens"], cached, u["cost"]

for i in (1, 2):
    prompt_tokens, cached, cost = ask()
    print(f"вызов {i}: prompt={prompt_tokens} cached={cached} cost=${cost:.6f}")
```

Команда: `python3 prompt_cache.py`

Ожидаемый вывод (реальный прогон):

```
вызов 1: prompt=10818 cached=0 cost=$0.013543
вызов 2: prompt=10818 cached=10801 cost=$0.001122
```

Шаг пройден, если во втором вызове `cached` заметно больше нуля и `cost` заметно ниже, чем в первом. Числа токенов и стоимости будут немного отличаться от прогона к прогону из-за версии модели, важна сама разница между вызовом 1 и 2.

## Шаг 2. Sticky-роутинг (sticky_session.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]
MODEL = "meta-llama/llama-3.3-70b-instruct"

def call(extra):
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "ок"}], "max_tokens": 5}
    payload.update(extra)
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["provider"]

pinned = [call({"session_id": "orders-bot-42"}) for _ in range(6)]
default = [call({}) for _ in range(6)]

print("session_id:", pinned, "->", len(set(pinned)), "провайдер")
print("default:   ", default, "->", len(set(default)), "провайдера")
```

Команда: `python3 sticky_session.py`

Ожидаемый вывод (реальный прогон):

```
session_id: ['Crusoe','Crusoe','Crusoe','Crusoe','Crusoe','Crusoe'] -> 1 провайдер
default:    ['Crusoe','DeepInfra','AkashML','AkashML','AkashML','Cloudflare'] -> 4 провайдера
```

Шаг пройден, если строка с `session_id` показывает ровно 1 уникального провайдера, а строка `default` показывает 2 и более. Конкретные имена провайдеров в вашем прогоне будут другими, важно соотношение количества уникальных значений.

## Шаг 3. Каскад по сложности задачи (model_cascade.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

CHEAP = "openai/gpt-4o-mini"
STRONG = "openai/gpt-4o"

def is_hard(prompt):
    markers = ("докажи", "проанализируй", "спроектируй", "выведи формулу")
    return len(prompt) > 200 or any(m in prompt.lower() for m in markers)

def route(prompt):
    model = STRONG if is_hard(prompt) else CHEAP
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        extra_body={"usage": {"include": True}},
    )
    cost = getattr(resp.usage, "cost", None)
    if cost is None:
        cost = (resp.usage.model_extra or {}).get("cost")
    return model, cost

tasks = [
    "Переведи слово cat на русский",
    "Проанализируй риски миграции монолита на микросервисы и предложи план",
]
for t in tasks:
    model, cost = route(t)
    print(f"{model:<20} cost=${cost:.6f}  <- {t[:40]}")
```

Команда: `python3 model_cascade.py`

Ожидаемый вывод (реальный прогон):

```
openai/gpt-4o-mini   cost=$0.000019  <- Переведи слово cat на русский
openai/gpt-4o        cost=$0.000673  <- Проанализируй риски миграции монолита
```

Шаг пройден, если для простой фразы выбралась `gpt-4o-mini`, для аналитической - `gpt-4o`, и стоимость второй заметно выше первой.

## Шаг 4. Субагент (subagent_demo.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]
ORCH = "openai/gpt-4o"
WORKER = "openai/gpt-4o-mini"

task = (
    "Составь короткий пресс-релиз про запуск нашего API. "
    "Рутинную часть, резюме из трёх буллетов по фактам, делегируй воркеру: "
    "единый ключ, 300+ моделей, оплата криптой. Затем собери финальный абзац сам."
)

payload = {
    "model": ORCH,
    "messages": [{"role": "user", "content": task}],
    "tools": [{
        "type": "openrouter:subagent",
        "parameters": {
            "model": WORKER,
            "instructions": "Ты быстрый воркер. Выполни задачу точно и кратко.",
            "max_completion_tokens": 200,
        },
    }],
    "max_tokens": 400,
    "usage": {"include": True},
}

r = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    json=payload,
    timeout=120,
)
r.raise_for_status()
j = r.json()
u = j["usage"]
st = u.get("server_tool_use_details", {})

print("делегировано воркеру:", st.get("tool_calls_executed"), "раз")
print(f"общая стоимость запроса: ${u['cost']:.6f}")

models = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {key}"},
    timeout=60,
).json()["data"]

def price_in(mid):
    return float(next(x for x in models if x["id"] == mid)["pricing"]["prompt"]) * 1e6

po, pw = price_in(ORCH), price_in(WORKER)
print(f"вход $/М: оркестратор {po}, воркер {pw} (воркер дешевле в ~{po / pw:.0f} раз)")
```

Команда: `python3 subagent_demo.py`

Ожидаемый вывод (реальный прогон):

```
делегировано воркеру: 1 раз
общая стоимость запроса: $0.004565
вход $/М: оркестратор 2.5, воркер 0.15 (воркер дешевле в ~17 раз)
```

Шаг пройден, если `делегировано воркеру` больше нуля и цена воркера ощутимо ниже цены оркестратора.

## Шаг 5. Контроль расхода (spend_limit.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]
headers = {"Authorization": f"Bearer {key}"}

k = httpx.get("https://openrouter.ai/api/v1/auth/key", headers=headers, timeout=15).json()["data"]
c = httpx.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=15).json()["data"]

print("лимит ключа:      ", k["limit"])
print("остаток лимита:   ", k["limit_remaining"])
print(f"расход за день:    {k['usage_daily']:.6f}")
print(f"расход за месяц:   {k['usage_monthly']:.6f}")
print(f"баланс аккаунта:   {c['total_credits']:.4f}, потрачено {c['total_usage']:.6f}")
```

Команда: `python3 spend_limit.py`

Ожидаемый вывод (реальный прогон):

```
лимит ключа:       None
остаток лимита:    None
расход за день:    0.057796
расход за месяц:   0.057831
баланс аккаунта:   10.0000, потрачено 0.057831
```

Шаг пройден, если приходят все пять строк без ошибки авторизации. `лимит ключа: None` означает отсутствие жёсткого потолка, это нормальное значение для ключа без лимита.

## Что делать если не так

- `prompt_cache.py`: `cached` во втором вызове равен 0 - кэш провайдера уже остыл (обычно живёт минуты) или провайдер сменился между вызовами, session_id должен быть одним и тем же.
- `sticky_session.py`: с `session_id` провайдеров больше 1 - либо у модели сейчас доступен только один провайдер и разница не проявится, либо TTL привязки истёк между запросами.
- `subagent_demo.py`: `tool_calls_executed` равен 0 - модель посчитала задачу слишком простой для делегирования, усложните формулировку задачи.
- Любой скрипт падает с `KeyError` на `usage`: добавьте в payload `"usage": {"include": True}`, без этого поля провайдер может не прислать детали кэша и стоимости.
