# Active metadata

Код к статье [Active metadata](https://bigdataschool.ru/wiki/active_metadata/).

Цикл активных метаданных на одном PostgreSQL 18.6 и Python, без каталога и брокера, чтобы механизм
был виден целиком. Event trigger на `ddl_command_end` и `sql_drop` пишет каждое изменение схемы в
журнал `meta.events` и отправляет id события через `pg_notify`. Слушатель на psycopg получает id
через `LISTEN`, читает событие, применяет правила и сам меняет базу: ставит тег `pii`, передаёт его
по lineage на зависимые представления, отзывает `SELECT` у роли аналитика, а при удалении колонки
находит сломанных внешних потребителей. Для сравнения рядом пассивный каталог, который обходит
`information_schema` по расписанию и пропускает то, что случилось между обходами.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker, порт `127.0.0.1:55441`, схема из `setup.sql` при первом старте |
| `requirements.txt` | `psycopg[binary]==3.3.8` |
| `setup.sql` | схемы `raw`, `mart`, `report`, роль `analyst`, служебная схема `meta` (события, колонки, lineage, теги, действия), функции и event trigger |
| `passive_vs_active.py` | два обхода каталога против событий; откат транзакции; слушатель, который был отключён, и догон по журналу |
| `active_actions.py` | правила `pii_by_name`, `pii_propagation`, `impact_on_drop`, фильтр собственных событий, проверка прав аналитика |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `postgres:18.6`, Python 3.10 или новее.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python passive_vs_active.py
.venv/bin/python active_actions.py
docker compose down -v
```

Каждый скрипт начинает с пересоздания `raw.customers` и пустого журнала, порядок запуска не важен.
