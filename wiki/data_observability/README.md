# Наблюдаемость данных (Data Observability)

Код к статье: https://bigdataschool.ru/wiki/data_observability/

Демо на Soda Core и PostgreSQL. Витрина заказов проходит три состояния, на каждом
прогоняются одни и те же правила, метрики складываются в историю, а отдельный детектор
ищет отклонение от базовой линии и считает масштаб последствий по графу происхождения.

## Состав

| Файл | Что делает |
|---|---|
| `demo_setup.py` | пересоздаёт базу `observability_demo`, наполняет 30 дней истории заказов |
| `configuration.yml` | подключение Soda Core к источнику PostgreSQL |
| `checks.yml` | правила SodaCL: свежесть, объём, схема, пропуски, словарь статусов |
| `demo_scan.py` | три скана подряд с поломкой витрины между ними, запись метрик в историю |
| `demo_baseline.py` | детекция аномалии по медиане и MAD, оценка затронутых потребителей |
| `RUNBOOK.md` | подробная инструкция по шагам |

## Окружение

Python 3.12, soda-core 3.5.6, soda-core-postgres 3.5.6, psycopg 3.3.4, PostgreSQL 18.4.

## Запуск

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install soda-core-postgres==3.5.6 psycopg[binary]==3.3.4
# правим host, port и username в configuration.yml
./.venv/bin/python3 demo_setup.py
./.venv/bin/python3 demo_scan.py
./.venv/bin/python3 demo_baseline.py
```

Подробности и разбор вывода в `RUNBOOK.md`.
