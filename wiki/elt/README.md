# ELT (Extract, Load, Transform)

Код к статье [ELT (Extract, Load, Transform)](https://bigdataschool.ru/wiki/elt/).

Демо показывает ELT целиком: Extract читает сырую таблицу источника как есть, Load копирует её
построчно в целевую базу без единой правки, Transform — один SQL-запрос, который выполняет сам
Postgres после загрузки (дедупликация, чистка региона, отсев брака, бизнес-фильтр, расчёт
выручки, агрегация). Никакого pandas между extract и load, в отличие от ETL-демо.

## Состав

| Файл | Что внутри |
|---|---|
| `db_setup.py` | Создаёт демо-базу `elt_demo` и таблицу `source.orders` — имитацию OLTP-источника, 5000 строк плюс намеренные дефекты: дубли от повторной выгрузки, пропуски в количестве и цене, разнобой в написании региона |
| `elt_pipeline.py` | Сам конвейер: `extract_and_load()` копирует `source.orders` в `raw.orders_raw` построчно и без очистки, `transform()` одним SQL-запросом строит `analytics.sales_summary` — дедуп, чистка, фильтр по статусу, выручка, агрегация по региону и дате |
| `RUNBOOK.md` | Пошаговое воспроизведение с ожидаемым выводом на каждом шаге |

## Окружение

Python 3.12, `psycopg[binary]` 3.3.4, локальный PostgreSQL 18.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install "psycopg[binary]==3.3.4"

./.venv/bin/python3 db_setup.py
./.venv/bin/python3 elt_pipeline.py
```

Подробности по каждому шагу, ожидаемый вывод и типовые грабли лежат в `RUNBOOK.md`.
