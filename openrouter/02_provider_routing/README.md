# Маршрутизация провайдеров и фолбэк

Код к статье «Маршрутизация провайдеров и фолбэк» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-provider-routing-fallback/

## Состав
- `provider_sort.py` - сортировка провайдеров по цене и по пропускной способности.
- `provider_order.py` - свой порядок провайдеров и запрет фолбэка.
- `model_fallback.py` - резерв по моделям: переключение на вторую модель при сбое первой.
- `auto_router.py` - auto-роутер `openrouter/auto`, роутер сам подбирает модель.
- `rankings_top.py` - топ моделей по объёму токенов за день через датасет-эндпоинт.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакеты `openai`, `httpx`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`.

## Как запустить
1. Установить зависимости: `pip install openai httpx`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить любой файл: `python3 provider_sort.py` и так далее.
