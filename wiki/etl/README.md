# ETL (Extract, Transform, Load)

Код к статье [ETL (Extract, Transform, Load)](https://bigdataschool.ru/wiki/etl/).

Демо показывает классический ETL целиком: Extract читает сырую таблицу источника как есть,
Transform чистит (дубли, пропуски, разнобой в написании) и агрегирует данные в pandas — вне
базы, Load полностью перезаписывает целевую таблицу результатом (full load).

## Состав

| Файл | Что внутри |
|---|---|
| `db_setup.py` | Создаёт демо-базу `etl_demo` и таблицу `raw_orders` — 5000 строк источника плюс намеренные дефекты: дубли от повторной выгрузки, пропуски в количестве и цене, разнобой в написании региона |
| `etl_pipeline.py` | Сам конвейер: `extract()` выгружает `raw_orders`, `transform()` чистит/фильтрует/считает выручку/агрегирует по региону и дате, `load()` перезаписывает `sales_summary` целиком |
| `RUNBOOK.md` | Пошаговое воспроизведение с ожидаемым выводом на каждом шаге |

## Окружение

Python 3.12, `pandas` 3.0.5, `psycopg[binary]` 3.3.4, локальный PostgreSQL 18.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install "pandas==3.0.5" "psycopg[binary]==3.3.4"

./.venv/bin/python3 db_setup.py
./.venv/bin/python3 etl_pipeline.py
```

Подробности по каждому шагу, ожидаемый вывод и типовые грабли лежат в `RUNBOOK.md`.
