# pg_clickhouse

Код к статье https://bigdataschool.ru/wiki/pg_clickhouse/

Docker-стенд с PostgreSQL (расширение pg_clickhouse) и ClickHouse рядом:
подключение ClickHouse как foreign server через Foreign Data Wrapper
`clickhouse_fdw` и три проверенных на практике случая query pushdown —
успешный (WHERE + GROUP BY + агрегат), неуспешный (JOIN локальной и
удалённой таблицы) и переполнение типа (UInt64 vs bigint).

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | поднимает ClickHouse (`clickhouse/clickhouse-server:25.8`) и PostgreSQL с встроенным pg_clickhouse (`ghcr.io/clickhouse/pg_clickhouse:18`) |
| `clickhouse_setup.sql` | создаёт в ClickHouse таблицу `analytics.events` (1 млн синтетических событий) и представление с `toString()`-обходом переполнения UInt64 |
| `foreign_setup.sql` | `CREATE EXTENSION`, `CREATE SERVER`, `CREATE USER MAPPING`, `IMPORT FOREIGN SCHEMA` — подключает ClickHouse как foreign server в PostgreSQL |
| `pushdown_demo.sql` | `EXPLAIN (VERBOSE)` на успешном pushdown, на JOIN local↔remote (не проталкивается) и демонстрация ошибки/обхода переполнения UInt64 |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых ошибок |

## Окружение

Docker, Docker Compose. Проверено на Docker Desktop (macOS, arm64),
Compose v5.3.1.

## Как запустить

```bash
docker compose up -d
docker exec -i pg_clickhouse_ch clickhouse-client \
  --user default --password demo_pass --multiquery < clickhouse_setup.sql
docker exec -i pg_clickhouse_pg psql -U postgres < foreign_setup.sql
docker exec -i pg_clickhouse_pg psql -U postgres < pushdown_demo.sql
```

Подробности по каждому шагу, ожидаемый вывод и разбор граблей — в `RUNBOOK.md`.
