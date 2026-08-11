# Что такое LangGraph

Код к Wiki-статье «Что такое LangGraph» на сайте BigDataSchool: https://bigdataschool.ru/wiki/langgraph/

## Состав

- `agent_graph.py` — минимальный граф агента: состояние с редьюсером, узел модели, узел инструментов и цикл между ними через условное ребро
- `hitl_approval.py` — тот же граф с чекпоинтером SQLite и паузой на подтверждение человека через `interrupt` и `Command(resume=...)`
- `RUNBOOK.md` — пошаговый прогон с проверкой после каждого шага

## Окружение

- Python 3.14
- langgraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1
- langchain 1.3.14, langchain-ollama 1.1.0
- Ollama 0.32.9 на http://localhost:11434
- Модель с поддержкой вызова инструментов: qwen2.5:7b или llama3.1:8b

Внешние ключи и платные API не нужны, всё работает на локальной модели.

## Как запустить

1. Поставить зависимости: `pip install "langgraph==1.2.11" "langgraph-checkpoint-sqlite==3.1.1" "langchain==1.3.14" "langchain-ollama==1.1.0"`
2. Скачать модель: `ollama pull qwen2.5:7b`
3. Прогнать базовый граф: `python3 agent_graph.py`
4. Прогнать граф с паузой на подтверждение: `python3 hitl_approval.py`

Имя модели и адрес сервера переопределяются переменными окружения `OLLAMA_MODEL` и `OLLAMA_URL`. Подробный порядок с проверками в `RUNBOOK.md`.
