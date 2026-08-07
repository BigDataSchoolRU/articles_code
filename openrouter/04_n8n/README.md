# OpenRouter в n8n без кода

Код к статье «OpenRouter в n8n без кода» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-n8n-nocode/

## Состав
- `multimodal_onekey.py` - один ключ на текст, картинку, синтез речи и транскрипцию.
- `openrouter_n8n_content_flow.json` - готовый флоу n8n из трёх узлов (Запуск вручную, Тема, OpenRouter).
- `RUNBOOK.md` - пошаговый прогон с проверками, включая развёртывание self-hosted n8n.

## Окружение
Python 3.12, пакет `httpx`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`. Для n8n: self-hosted инстанс на своём сервере (n8n open-source, к конкретному облаку не привязан), Docker.

## Как запустить
1. Установить зависимости: `pip install httpx`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить `python3 multimodal_onekey.py`.
4. Для n8n: поднять инстанс через Docker, импортировать `openrouter_n8n_content_flow.json`, подставить ключ в узел OpenRouter. Подробности в RUNBOOK.md.
