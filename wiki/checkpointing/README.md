# Checkpointing: демо к статье

Код к статье «Checkpointing (Чекпоинтинг)»: https://bigdataschool.ru/wiki/checkpointing/

Демо показывает два механизма чекпоинтера LangGraph: восстановление графа после
реального падения процесса и time travel с форком выполнения по другой ветке.

## Файлы

| Файл | Что делает |
|---|---|
| `checkpointing_langgraph_crash_resume.py` | убивает процесс посреди графа (`os._exit`) и продолжает его тем же `thread_id` из SQLite-чекпоинтера |
| `checkpointing_langgraph_time_travel.py` | откатывается к более раннему чекпоинту и форкает выполнение по другой ветке, не трогая исходную |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Python 3.12, `langgraph` 1.2.11, `langgraph-checkpoint` 4.2.0,
`langgraph-checkpoint-sqlite` 3.1.1. Внешние сервисы не нужны — оба демо работают
на локальном файле SQLite.

## Как запустить

```bash
python3 -m pip install langgraph langgraph-checkpoint-sqlite
python3 checkpointing_langgraph_crash_resume.py
python3 checkpointing_langgraph_time_travel.py
```

Подробности по шагам и разбор вывода в `RUNBOOK.md`.
