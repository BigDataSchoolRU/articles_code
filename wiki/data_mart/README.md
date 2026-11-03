# Витрина данных

Код к статье [Витрина данных](https://bigdataschool.ru/wiki/data_mart/).

Витрина продаж на dbt + DuckDB: сырой слой `raw`, представления `staging`, витрина `marts` со
схемой «звезда» (измерение клиентов и факт продаж по дням). Один и тот же факт собран в двух
материализациях, `table` и `incremental`, чтобы на догрузке было видно, чем они отличаются.

## Состав

| Файл | Что делает |
|---|---|
| `requirements.txt` | пины dbt-core, dbt-duckdb, duckdb |
| `data/*.csv` | клиенты и две партии заказов; во второй есть опоздавший заказ за 2026-10-02 |
| `load_orders.py` | имитация EL-загрузки: кладёт партию заказов в схему `raw` файла `warehouse.duckdb` |
| `dbt_project.yml`, `profiles.yml` | проект dbt и подключение к локальному файлу DuckDB |
| `macros/generate_schema_name.sql` | схемы `staging` и `marts` без префикса профиля |
| `models/staging/` | источники и staging-представления заказов и клиентов |
| `models/marts/sales/dim_customers.sql` | измерение «клиент» |
| `models/marts/sales/fct_sales_daily.sql` | витрина продаж, `table`: пересчёт всей истории |
| `models/marts/sales/fct_sales_daily_incr.sql` | та же витрина, `incremental` (`delete+insert`) с окном `lookback_days` |
| `models/marts/sales/_sales.yml`, `tests/` | тесты ключей и зерна витрины |
| `compare_marts.py` | сверка выручки по дням между двумя материализациями |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Python 3.12, `dbt-core` 1.12.6, `dbt-duckdb` 1.11.1, `duckdb` 2.0.0. Docker и сервер БД не нужны:
хранилище это файл `warehouse.duckdb` рядом с проектом.

## Как запустить

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DBT_PROFILES_DIR=$PWD
.venv/bin/python load_orders.py 1
.venv/bin/dbt build
.venv/bin/python load_orders.py 2
.venv/bin/dbt run --select marts
.venv/bin/python compare_marts.py
.venv/bin/dbt run --select fct_sales_daily_incr --vars '{lookback_days: 3}'
.venv/bin/python compare_marts.py
```
