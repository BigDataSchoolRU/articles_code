# Reverse ETL

Код к статье [Reverse ETL](https://bigdataschool.ru/wiki/reverse_etl/).

Минимальный движок Reverse ETL без SaaS: модель в PostgreSQL, снимок прошлого прогона по
первичному ключу, diff через FULL OUTER JOIN и отправка только разницы батчами в имитацию CRM
с лимитом запросов.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker на порту 55433 |
| `init.sql` | витрина `analytics.customer_scores` на 25 клиентов и таблица снимка `reverse_etl.sync_snapshot` |
| `changes.sql` | изменения витрины между прогонами: два UPDATE, UPDATE без смены значений, INSERT, DELETE |
| `mock_crm.py` | имитация API CRM на стандартной библиотеке: upsert и delete по `external_id`, 2 запроса в секунду, сверх лимита 429 с `Retry-After` |
| `sync.py` | синхронизация: модель, diff со снимком, режимы `upsert` и `mirror`, батчи, повтор по 429, сдвиг снимка за каждым подтверждённым батчем |
| `requirements.txt` | `psycopg[binary]` 3.3.8 |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с Compose, Python 3.12, пакет `psycopg[binary]` 3.3.8.

## Как запустить

```bash
docker compose up -d --wait
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python mock_crm.py &
.venv/bin/python sync.py --sync contacts_mirror --mode mirror
docker compose exec -T dwh psql -U demo -d dwh < changes.sql
.venv/bin/python sync.py --sync contacts_mirror --mode mirror
kill %1 && docker compose down -v
```
