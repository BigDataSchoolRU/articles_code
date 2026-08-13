# Tool Calling

Код к Wiki-статье «Tool Calling» на сайте BigDataSchool: https://bigdataschool.ru/wiki/tool_calling/

## Состав

- `tool_calling_demo.py` — объявление двух инструментов в JSON Schema, диспетчер и агентный цикл на локальной модели через Ollama
- `tool_calling_guard.py` — валидация имени и аргументов вызова через pydantic плюс замер служебных токенов на каталог инструментов
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение

- Python 3.12.13
- ollama (python client) 0.6.2, pydantic 2.13.4
- Ollama 0.32.9 на `http://localhost:11434`, модель qwen2.5:7b

Внешние ключи и платные API не нужны, всё считается локально.

## Как запустить

1. Поднять Ollama и скачать модель: `ollama pull qwen2.5:7b`
2. Поставить зависимости: `pip install "ollama==0.6.2" "pydantic==2.13.4"`
3. Прогнать агентный цикл: `python3 tool_calling_demo.py`
4. Прогнать валидацию и замер токенов: `python3 tool_calling_guard.py`
