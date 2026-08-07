# RUNBOOK. OpenRouter против альтернатив

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, litellm 1.60.2. Ключ инференса OpenRouter в `OPENROUTER_API_KEY`, LiteLLM подхватывает его сам по префиксу модели `openrouter/`. Файл кода: `litellm_demo.py`.

## Шаг 1. Установка LiteLLM

```bash
pip install litellm --break-system-packages
```

Проверка: `python3 -c "import litellm; print(litellm.__version__)"` печатает версию без ошибок импорта.

## Шаг 2. Вызов OpenRouter через LiteLLM (litellm_demo.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, litellm 1.60.2, OpenRouter API
# LiteLLM как self-hosted слой: тем же ключом ходит в OpenRouter через префикс openrouter/.
import litellm

# Модель с префиксом openrouter/ говорит LiteLLM идти в OpenRouter.
# Ключ берётся из переменной окружения OPENROUTER_API_KEY автоматически.
r = litellm.completion(
    model="openrouter/openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
    max_tokens=10,
)

# Ответ в том же формате OpenAI, что и у прямого вызова OpenRouter.
print("litellm -> OpenRouter:", r.choices[0].message.content)
print("model:", r.model)
```

Команда: `python3 litellm_demo.py`

Ожидаемый вывод (реальный прогон):

```
litellm -> OpenRouter: Готово.
model: openrouter/openai/gpt-4o-mini
```

Шаг пройден, если ответ пришёл без ошибок авторизации и `model` содержит префикс `openrouter/`, подтверждающий, что LiteLLM реально ходил через OpenRouter, а не напрямую к OpenAI.

## Что делать если не так

- `ModuleNotFoundError: No module named 'litellm'`: не выполнен шаг 1, либо `pip` без флага `--break-system-packages` в этом окружении.
- Ошибка авторизации: LiteLLM ищет ключ в переменной `OPENROUTER_API_KEY` автоматически по префиксу модели `openrouter/`, проверьте, что переменная экспортирована в той же сессии терминала, где запускается скрипт.
- Ответ пришёл, но `model` без префикса `openrouter/`: значит вызов ушёл не туда, куда ожидалось, проверьте, что в имени модели явно указан префикс `openrouter/openai/gpt-4o-mini`, а не просто `gpt-4o-mini`.
