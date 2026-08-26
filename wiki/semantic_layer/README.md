# Semantic layer

Код к Wiki-статье «Semantic layer» — https://bigdataschool.ru/wiki/semantic_layer/

## Состав

- `db_setup.py` — пересоздаёт демо-базу PostgreSQL `semantic_layer_demo` с таблицей `orders`
- `dbt_project.yml` — конфигурация dbt-проекта
- `profiles.yml` — подключение к локальному Postgres (замените пользователя на своего)
- `models/staging/stg_orders.sql`, `models/staging/_sources.yml` — staging-слой над сырой таблицей
- `models/metricflow_time_spine.sql`, `models/_time_spine.yml` — календарная модель, обязательная для MetricFlow
- `models/semantic_models.yml` — семантическая модель: сущность, измерения, measures
- `models/metrics.yml` — метрики: `total_revenue`, `order_count`, `completion_rate` (ratio)

## Окружение

Python 3.12, PostgreSQL 13+, `dbt-core` 1.12.3, `dbt-postgres` 1.11.0, `dbt-metricflow` 0.14.0
(MetricFlow 0.212.0).

## Как запустить

Подробности и разбор типовых ошибок — в [RUNBOOK.md](./RUNBOOK.md). Коротко:

```bash
python3 -m venv .venv
./.venv/bin/pip install dbt-core dbt-postgres dbt-metricflow
./.venv/bin/python3 db_setup.py
export DBT_PROFILES_DIR=.
./.venv/bin/dbt build
./.venv/bin/mf query --metrics completion_rate --group-by order_id__region --explain
```
