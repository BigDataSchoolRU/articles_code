# RUNBOOK: dbt — DAG моделей, материализации, тесты

## Окружение

- Python 3.12+, `dbt-core` 1.12.3, `dbt-postgres` 1.11.0
- PostgreSQL 14+ (демо проверено на 18.4), доступный по TCP
- Пустая или тестовая база данных — dbt создаст в ней объекты `stg_orders` и `fct_daily_orders`

```bash
pip install dbt-core dbt-postgres
```

## Шаг 1. Исходные данные

Демо ожидает таблицу `orders` в схеме `public`:

```sql
CREATE TABLE orders (
    order_id     SERIAL PRIMARY KEY,
    customer_id  INTEGER NOT NULL,
    order_date   DATE NOT NULL,
    region       TEXT NOT NULL,
    status       TEXT NOT NULL,
    amount       NUMERIC(10, 2) NOT NULL
);
```

Заполните её любыми данными: `status` — одно из `completed`, `pending`, `cancelled`,
`refunded` (это же перечисление проверяет тест `accepted_values`), `region` — произвольная
строка.

## Шаг 2. Профиль подключения

`profiles.yml` уже в папке. Подставьте свои `host`, `user`, `password`, `dbname`:

```yaml
dbt_demo:
  target: dev
  outputs:
    dev:
      type: postgres
      host: <ваш-хост>
      user: <ваш-пользователь>
      password: "<ваш-пароль>"
      port: 5432
      dbname: <ваша-база>
      schema: public
      threads: 4
```

Проверка подключения:

```bash
DBT_PROFILES_DIR=. dbt debug
```

В выводе должно быть `All checks passed!`.

## Шаг 3. Построение DAG

```bash
DBT_PROFILES_DIR=. dbt build
```

Что должно быть в выводе: восемь шагов подряд — сначала `1 of 8` строит
`public.stg_orders` как VIEW, затем `5 of 8` строит `public.fct_daily_orders` как TABLE.
dbt сам поставил `stg_orders` раньше `fct_daily_orders`, потому что вторая модель
ссылается на первую через `{{ ref('stg_orders') }}` — это и есть граф зависимостей (DAG),
dbt не спрашивает порядок, он его вычисляет. Между двумя моделями проходят шесть тестов
(`not_null`, `unique`, `accepted_values`, `relationships`), все со статусом `PASS`.
Строка в самом конце: `Done. PASS=8 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=8`.

Как понять, что шаг прошёл: код возврата команды `0`, в логе нет строк `ERROR` или `FAIL`.

## Шаг 4. Проверка результата

```bash
psql -d <ваша-база> -c "select order_date, region, orders_count, completed_amount, total_amount from fct_daily_orders order by order_date, region limit 5;"
```

Ожидаемо: таблица `fct_daily_orders` уже физически существует (материализация `table`,
задана в `dbt_project.yml`) и содержит по одной строке на пару дата-регион с агрегатами
по заказам этого дня. `completed_amount` может быть пустым (`NULL`) для дня-региона, где
не было заказов со статусом `completed` — это нормальное поведение `sum(...) filter (...)`,
а не ошибка.

## Если не так

- **`Could not connect to server`** — проверьте `host`/`port` в `profiles.yml` и что
  PostgreSQL слушает указанный адрес.
- **`Runtime Error ... Database Error ... relation "orders" does not exist`** — таблица
  `orders` из шага 1 не создана в той базе, что указана в `profiles.yml`.
- **Deprecation-предупреждение `MissingArgumentsPropertyInGenericTestDeprecation` при
  `dbt parse`/`dbt build`** — актуально для dbt-core 1.12.x: аргументы generic-тестов
  (`accepted_values`, `relationships`) должны лежать под вложенным ключом `arguments`, а
  не на верхнем уровне теста. В `models/schema.yml` этого проекта уже сделано так; если
  переносите тест в свой проект и видите это предупреждение — заверните значения под
  `arguments:`.
- **`dbt debug` зависает или падает без понятной причины** — проверьте, что переменная
  `DBT_PROFILES_DIR` указывает на папку с `profiles.yml` (по умолчанию dbt ищет его в
  `~/.dbt/`, а не в папке проекта).
