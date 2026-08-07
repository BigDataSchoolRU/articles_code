# OpenRouter против альтернатив

Код к статье «OpenRouter против альтернатив» на сайте BigDataSchool: (URL появится после публикации)

## Состав
- `litellm_demo.py` - LiteLLM как self-hosted слой, ходит в OpenRouter через префикс модели `openrouter/`.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакет `litellm`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`, LiteLLM подхватывает его сам по префиксу модели.

## Как запустить
1. Установить зависимости: `pip install litellm`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить `python3 litellm_demo.py`.
