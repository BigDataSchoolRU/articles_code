# Идемпотентность

Код к статье [Идемпотентность](https://bigdataschool.ru/wiki/idempotency/).

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker на порту 55432 |
| `partition_reload.py` | загрузка партиции с падением, ретраем и перезапуском: наивный INSERT, перезапись партиции, upsert через ON CONFLICT |
| `idempotency_key_store.py` | обработчик POST /payments с таблицей ключей Idempotency-Key: повтор, гонка (409), чужое тело (422), нет ключа (400) |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с Compose, Python 3.12, пакет `psycopg[binary]` 3.3.7.

## Как запустить

```bash
docker compose up -d --wait
python3 -m venv .venv && .venv/bin/pip install "psycopg[binary]==3.3.7"
.venv/bin/python partition_reload.py
.venv/bin/python idempotency_key_store.py
docker compose down -v
```
