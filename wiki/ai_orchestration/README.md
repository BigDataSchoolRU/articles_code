# Оркестрация ИИ (AI Orchestration)

Код к статье: https://bigdataschool.ru/wiki/ai_orchestration/

Supervisor-граф на LangGraph поверх локальной модели qwen2.5:7b в Ollama. Состояние графа
после каждого суперстепа сохраняется в SQLite, второй сценарий показывает обрыв процесса и
возобновление работы с того же `thread_id`.

## Состав

| Файл | Что делает |
|---|---|
| `supervisor_graph.py` | граф из супервизора и двух исполнителей, чекпоинтер в SQLite, разбор истории чекпоинтов |
| `resume_demo.py` | запускает граф в отдельном процессе, убивает его сигналом KILL после первого исполнителя и доигрывает из снимка состояния |
| `requirements.txt` | версии пакетов, на которых прогонялось демо |
| `RUNBOOK.md` | пошаговая инструкция запуска с признаками успеха и типовыми граблями |

## Окружение

Python 3.12, LangGraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1, langchain-ollama 1.1.0,
Ollama 0.32.13 с моделью qwen2.5:7b. Внешних сервисов и Docker не требуется.

## Запуск

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt
ollama pull qwen2.5:7b
./.venv/bin/python3 supervisor_graph.py
./.venv/bin/python3 resume_demo.py
```

Подробности по шагам и разбор вывода в `RUNBOOK.md`.
