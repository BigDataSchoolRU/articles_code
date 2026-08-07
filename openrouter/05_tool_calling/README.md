# Tool calling, структурированный вывод и агенты

Код к статье «Tool calling, структурированный вывод и агенты» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-tool-calling-structured-output-agents/

## Состав
- `tool_calling.py` - базовый tool calling: модель просит вызвать функцию, мы исполняем.
- `agent_loop.py` - многошаговый агентный цикл с несколькими зависимыми инструментами.
- `structured_output.py` - структурированный вывод по строгой JSON-схеме.
- `response_healing.py` - плагин Response Healing, чинит битый JSON до приложения.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакет `openai`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`.

## Как запустить
1. Установить зависимости: `pip install openai`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить любой файл, например `python3 tool_calling.py`.
