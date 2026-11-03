# RUNBOOK: витрина продаж на dbt + DuckDB

## Окружение

- Linux или macOS, Python 3.12+
- `dbt-core` 1.12.6, `dbt-duckdb` 1.11.1, `duckdb` 2.0.0 (пины в `requirements.txt`)
- Сервер БД не нужен: хранилище это файл `warehouse.duckdb` в папке проекта
- Проверено на Ubuntu 24.04, Python 3.12.3, 2026-11-03

Все команды выполняются из папки проекта.

## Шаг 1. Окружение

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DBT_PROFILES_DIR=$PWD
.venv/bin/dbt --version
```

В выводе `installed: 1.12.6` и `duckdb: 1.11.1`. dbt может напечатать, что доступна линия v2:
для этого проекта это не ошибка, он проверен на v1.

## Шаг 2. Первая загрузка сырого слоя

```bash
.venv/bin/python load_orders.py 1
```

Ожидаемо: `партия 1: в raw.orders строк=10, последний день=2026-10-03`. Рядом появился файл
`warehouse.duckdb`.

## Шаг 3. Сборка витрины и тесты

```bash
.venv/bin/dbt build
```

dbt строит по графу зависимостей: представления `staging.stg_customers` и `staging.stg_orders`,
таблицу `marts.dim_customers`, затем обе версии факта и прогоняет тесты. Шаг прошёл, если в
конце `Done. PASS=10 WARN=0 ERROR=0`.

```bash
.venv/bin/python compare_marts.py
```

```
день               table   incremental
2026-10-01      22200.00      22200.00
2026-10-02      18500.00      18500.00
2026-10-03      11100.00      11100.00
...
дней с расхождением: 0
```

На первом запуске incremental-модель строится целиком, поэтому совпадает с table.

## Шаг 4. Догрузка с опоздавшим заказом

```bash
.venv/bin/python load_orders.py 2
.venv/bin/dbt run --select marts
.venv/bin/python compare_marts.py
```

Вторая партия приносит заказы за 2026-10-04 и 2026-10-05 и один заказ за 2026-10-02, который
пришёл с опозданием. Ожидаемо:

```
2026-10-02      23500.00      18500.00   <-- расхождение
...
дней с расхождением: 1
```

Таблица пересчитала всю историю и увидела опоздавший заказ. Incremental-модель с
`lookback_days: 0` взяла только дни начиная с последнего загруженного (2026-10-03) и про
2026-10-02 не узнала. Фильтр виден в `target/compiled/data_mart_demo/models/marts/sales/fct_sales_daily_incr.sql`:

```sql
where o.order_date >= (
    select max(sale_date) - 0 from "warehouse"."marts"."fct_sales_daily_incr"
)
```

## Шаг 5. Окно пересчёта

```bash
.venv/bin/dbt run --select fct_sales_daily_incr --vars '{lookback_days: 3}'
.venv/bin/python compare_marts.py
.venv/bin/dbt test
```

Теперь incremental пересчитывает последние три дня до максимума, стратегия `delete+insert`
удаляет строки этих дней по ключу зерна и вставляет заново. Ожидаемо `дней с расхождением: 0`
и `Done. PASS=5` у тестов, включая `assert_sales_grain_unique`: дублей зерна после пересчёта нет.

## Если не так

- **`Invalid value for '--profiles-dir': Path '~/.dbt' does not exist`.** dbt запущен не из
  папки проекта и не нашёл `profiles.yml`. Перейдите в папку проекта или выполните
  `export DBT_PROFILES_DIR=<путь к проекту>`.
- **`IO Error: Could not set lock on file ".../warehouse.duckdb": Conflicting lock is held`.** Файл открыт другим процессом
  (DBeaver, второй терминал с `duckdb`). DuckDB допускает одного писателя: закройте соединение.
- **Расхождение не исчезло после шага 5.** Заказ опоздал дальше окна `lookback_days`. Увеличьте
  окно или пересоберите модель целиком: `dbt run --select fct_sales_daily_incr --full-refresh`.
- **Повторный прогон с нуля.** Удалите `warehouse.duckdb` и папку `target/`, начните с шага 2.
  `load_orders.py 2` дописывает строки, поэтому без сброса заказы второй партии задвоятся в `raw`.
