# Multi-Agent System (мультиагентная система)

Код к Wiki-статье «Multi-Agent System (мультиагентная система)» на сайте BigDataSchool: https://bigdataschool.ru/wiki/multi_agent_system/

## Состав
- `supervisor_demo.py` — мультиагентная система с супервизором на LangGraph: диспетчер, поисковик, аналитик, контролёр.
- `cost_compare.py` — та же задача одним агентом и командой из трёх агентов, со счётчиком токенов и времени.
- `RUNBOOK.md` — пошаговый прогон с проверками.

## Окружение
- Python 3.12
- langgraph 1.2.11, langchain-core 1.5.4, langchain-ollama 1.1.0
- Ollama 0.32.9 с моделью qwen2.5:7b (нужна поддержка вызова инструментов и русского языка)

## Как запустить
1. Создать окружение и поставить зависимости: `python3 -m venv .venv && ./.venv/bin/pip install langgraph langchain-ollama`
2. Убедиться, что Ollama отвечает: `curl -s http://localhost:11434/api/tags`
3. Скачать модель: `ollama pull qwen2.5:7b`
4. Запустить демо: `./.venv/bin/python3 supervisor_demo.py` и `./.venv/bin/python3 cost_compare.py`
