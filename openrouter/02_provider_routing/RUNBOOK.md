# RUNBOOK. Маршрутизация провайдеров и фолбэк

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, openai 2.53.0, httpx 0.28.1. Ключ в `OPENROUTER_API_KEY`. Файлы кода: `provider_sort.py`, `provider_order.py`, `model_fallback.py`, `rankings_top.py`, `auto_router.py`. Модель для демо-запросов с несколькими провайдерами: `meta-llama/llama-3.3-70b-instruct`, у неё их достаточно, чтобы увидеть разницу в маршрутизации.

## Шаг 1. Сортировка провайдеров по цене и по скорости (provider_sort.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

MODEL = "meta-llama/llama-3.3-70b-instruct"

for sort_by in ("price", "throughput"):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
        max_tokens=20,
        extra_body={"provider": {"sort": sort_by}},
    )
    print(f"sort={sort_by:<11} provider={resp.provider}")
```

Команда: `python3 provider_sort.py`

Ожидаемый вывод (реальный прогон):

```
sort=price       provider=DeepInfra
sort=throughput  provider=SambaNova
```

Шаг пройден, если провайдер для `sort=price` и `sort=throughput` разный, либо совпадает, но оба значения непустые. Конкретные имена провайдеров могут смениться от прогона к прогону, каталог живой, это ожидаемо.

## Шаг 2. Свой порядок провайдеров без фолбэка (provider_order.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

MODEL = "meta-llama/llama-3.3-70b-instruct"

resp = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
    max_tokens=20,
    extra_body={"provider": {"order": ["Together", "DeepInfra"], "allow_fallbacks": False}},
)

print("provider:", resp.provider)
```

Команда: `python3 provider_order.py`

Ожидаемый вывод (реальный прогон): `provider: Together`. Шаг пройден, если провайдер оказался первым из списка `order`. Если Together окажется недоступен и `allow_fallbacks=False`, запрос упадёт ошибкой, а не уйдёт к чужому провайдеру, это и есть проверяемое поведение.

## Шаг 3. Резерв по моделям (model_fallback.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

FALLBACK = ["meta-llama/llama-3.3-70b-instruct", "openai/gpt-4o-mini"]
messages = [{"role": "user", "content": "Ответь одним словом: готово"}]

normal = client.chat.completions.create(
    model=FALLBACK[0],
    messages=messages,
    max_tokens=20,
    extra_body={"models": FALLBACK},
)
print("обычный вызов -> ответила:", normal.model, "| провайдер:", normal.provider)

forced = client.chat.completions.create(
    model=FALLBACK[0],
    messages=messages,
    max_tokens=20,
    extra_body={"models": FALLBACK, "provider": {"only": ["OpenAI"]}},
)
print("сбой первой   -> ответила:", forced.model, "| провайдер:", forced.provider)
```

Команда: `python3 model_fallback.py`

Ожидаемый вывод (реальный прогон):

```
обычный вызов -> ответила: meta-llama/llama-3.3-70b-instruct | провайдер: Novita
сбой первой   -> ответила: openai/gpt-4o-mini | провайдер: OpenAI
```

Шаг пройден, если во второй строке модель сменилась на вторую из списка `FALLBACK`, потому что первую с ограничением `only: ["OpenAI"]` обслужить некому.

## Шаг 4. Auto-роутер (auto_router.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

resp = client.chat.completions.create(
    model="openrouter/auto",
    messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
    max_tokens=20,
)

print("реально ответила модель:", resp.model, "| провайдер:", resp.provider)
```

Команда: `python3 auto_router.py`

Ожидаемый вывод (реальный прогон): `реально ответила модель: openai/gpt-5.6-sol | провайдер: OpenAI`. Шаг пройден, если `resp.model` не равен строке `openrouter/auto`, а показывает реальную модель, которую подобрал роутер. Конкретная модель зависит от каталога на момент запроса и будет отличаться.

## Шаг 5. Топ моделей по токенам за день (rankings_top.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]
day = "2026-08-03"

r = httpx.get(
    "https://openrouter.ai/api/v1/datasets/rankings-daily",
    params={"start_date": day, "end_date": day},
    headers={"Authorization": f"Bearer {key}"},
    timeout=30,
)
r.raise_for_status()

rows = r.json()["data"]
rows = [x for x in rows if x["model_permaslug"] != "other"][:10]

print(f"Топ-10 моделей OpenRouter за {day} по токенам:")
for i, x in enumerate(rows, 1):
    tokens = int(x["total_tokens"])
    print(f"{i:>2}. {x['model_permaslug']:<45} {tokens/1e9:>8.1f}B")
```

Команда: `python3 rankings_top.py`

Ожидаемый вывод (реальный прогон, топ-3 для контроля):

```
Топ-10 моделей OpenRouter за 2026-08-03 по токенам:
 1. deepseek/deepseek-v4-flash-20260731             1015.8B
 2. deepseek/deepseek-v4-flash-20260423              950.7B
 3. tencent/hy3-20260706                             880.3B
```

Шаг пройден, если печатается 10 строк с числами в миллиардах, отсортированных по убыванию. Если прогоняете на другую дату, замените `day`, состав топа будет другим, это ожидаемо.

## Что делать если не так

- Все запросы падают с 401: проверьте `OPENROUTER_API_KEY`.
- `provider_order.py` падает ошибкой вместо ответа: у обоих провайдеров из списка в этот момент нет мощности, попробуйте другую пару или уберите `allow_fallbacks: False` для проверки связи.
- `rankings_top.py` возвращает пустой список: дата в будущем или слишком старая, датасет ещё не посчитан или уже архивирован, возьмите вчерашнюю дату.
- Значения `provider` каждый раз новые: это нормально, каталог провайдеров живой, важно само наличие ответа и корректность полей, а не конкретное имя.
