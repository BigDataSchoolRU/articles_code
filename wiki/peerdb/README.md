# PeerDB

Код к статье [PeerDB](https://bigdataschool.ru/wiki/peerdb/) — CDC-репликация из PostgreSQL
в ClickHouse через self-hosted PeerDB v0.37.5.

## Файлы

- `clickhouse_target_compose.yml` — отдельный ClickHouse-приёмник в сети `peerdb_network`, официальный quickstart-стек PeerDB его не включает.
- `source_schema.sql` — демо-таблица `orders` в исходном Postgres (20 строк).
- `peerdb_mirror.sql` — Nexus SQL: peer источника, peer ClickHouse, CDC-mirror.
- `cdc_dedup_demo.sh` — меняет данные в источнике и показывает дубли/soft-delete в `ReplacingMergeTree` до фонового merge, а также два способа получить корректный срез (`FINAL`, `argMax`).

## Окружение

Docker Compose v2, PostgreSQL-клиент `psql`, `curl`, `bc`. Подробности и порты — в `RUNBOOK.md`.

## Запуск

1. Поднять self-hosted PeerDB (официальный репозиторий `PeerDB-io/peerdb`, шаг 1 в `RUNBOOK.md`).
2. `docker compose -f clickhouse_target_compose.yml up -d`
3. `psql 'postgresql://postgres:postgres@localhost:9901/postgres' -f source_schema.sql`
4. `psql 'postgresql://postgres:peerdb@localhost:9900/postgres' -f peerdb_mirror.sql`
5. `./cdc_dedup_demo.sh`

Подробно, с ожидаемым выводом и разбором граблей — в `RUNBOOK.md`.
