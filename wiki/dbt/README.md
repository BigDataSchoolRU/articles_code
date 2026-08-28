# dbt — DAG моделей, материализации, тесты

Код к статье [dbt](https://bigdataschool.ru/wiki/dbt/) на BigDataSchool Wiki.

## Файлы

- `dbt_project.yml` — конфиг проекта: пути моделей, материализации по умолчанию для слоёв
  `staging` (view) и `marts` (table)
- `profiles.yml` — профиль подключения к PostgreSQL (пример, подставьте свои значения)
- `models/staging/_sources.yml` — объявление источника: таблица `orders`
- `models/staging/stg_orders.sql` — staging-модель, приводит сырую таблицу к чистому виду
- `models/marts/fct_daily_orders.sql` — mart-модель, агрегирует staging через `ref()`
- `models/schema.yml` — тесты `not_null`, `unique`, `accepted_values`, `relationships`
- `RUNBOOK.md` — как поднять демо на своей машине

## Окружение

`dbt-core` 1.12.3, `dbt-postgres` 1.11.0, PostgreSQL 18.4. Подробности и грабли — в
`RUNBOOK.md`.

## Запуск

```bash
DBT_PROFILES_DIR=. dbt build
```
