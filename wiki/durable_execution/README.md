# Durable Execution: демо к статье

Код к статье «Durable Execution»: https://bigdataschool.ru/wiki/durable_execution/

Демо на библиотеке DBOS показывает ядро паттерна: workflow из трёх шагов переживает
жёсткий крах процесса и восстанавливается сам на следующем запуске, без ручного кода
восстановления, а уже выполненные шаги при этом не повторяются.

## Файлы

| Файл | Что делает |
|---|---|
| `db_setup.py` | создаёт демо-базу `durable_execution_demo` и таблицу `side_effects` для проверки, сколько раз реально выполнился каждый шаг |
| `workflow_recovery_demo.py` | workflow из трёх шагов на DBOS; режим `start` запускает его (и может быть убит `kill -9` снаружи), режим `recover` показывает автоматическое восстановление после краха |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Python 3.12, `dbos` 2.31.0, `psycopg[binary]` 3.3.4. Нужен доступный PostgreSQL
(проверено на 18.4) — DBOS хранит в нём и свою служебную схему `dbos`, и прикладную
таблицу `side_effects` из демо.

## Как запустить

```bash
python3 -m pip install dbos "psycopg[binary]"
python3 db_setup.py
python3 -u workflow_recovery_demo.py start
```

Полный сценарий с крахом процесса и восстановлением — в `RUNBOOK.md`.
