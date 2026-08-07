# Экономика токенов: кэш, sticky-роутинг, каскад, субагенты

Код к статье «Экономика токенов: кэш, sticky-роутинг, каскад, субагенты» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-token-economics-cache-subagents/

## Состав
- `prompt_cache.py` - кэш промптов: второй вызов с тем же контекстом дешевле.
- `sticky_session.py` - sticky-роутинг: `session_id` держит запросы у одного провайдера.
- `model_cascade.py` - каскад: простые задачи на дешёвую модель, сложные на сильную.
- `subagent_demo.py` - субагент: флагман сбрасывает рутину на дешёвого воркера.
- `spend_limit.py` - контроль расхода по ключу и по балансу аккаунта.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакеты `openai`, `httpx`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`.

## Как запустить
1. Установить зависимости: `pip install openai httpx`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить любой файл, например `python3 prompt_cache.py`.
