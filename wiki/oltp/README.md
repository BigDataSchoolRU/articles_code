# OLTP

Код к статье [OLTP](https://bigdataschool.ru/wiki/oltp/).

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker на порту 55433 |
| `pgbench_load.sh` | нагрузка pgbench tpcb-like: TPS при 1, 4 и 16 клиентах и горячая строка (scale 1 против scale 16) |
| `serialization_retry.py` | две конкурирующие транзакции: потерянное обновление на READ COMMITTED, SQLSTATE 40001 и повтор на REPEATABLE READ, перекос записи и SSI на SERIALIZABLE |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с Compose, Python 3.12, пакет `psycopg[binary]` 3.3.7. pgbench идёт в образе `postgres:18.6`,
отдельно ставить его не нужно.

## Как запустить

```bash
docker compose up -d --wait
./pgbench_load.sh
python3 -m venv .venv && .venv/bin/pip install "psycopg[binary]==3.3.7"
.venv/bin/python serialization_retry.py
docker compose down -v
```
