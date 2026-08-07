# OpenRouter за 15 минут: ключ, первый запрос, оплата из России

Код к статье «OpenRouter за 15 минут: ключ, первый запрос, оплата из России» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-start-key-first-request-payment/

## Состав
- `first_request.py` - первый запрос к модели через OpenRouter одним OpenAI-совместимым клиентом.
- `check_credits.py` - проверка баланса и расхода по ключу через эндпоинт `/credits`.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакеты `openai`, `httpx`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`, в код не вписывается.

## Как запустить
1. Установить зависимости: `pip install openai httpx`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить `python3 first_request.py` и `python3 check_credits.py`.
