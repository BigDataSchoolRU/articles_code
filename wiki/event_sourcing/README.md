# Event Sourcing

Код к статье [Event Sourcing](https://bigdataschool.ru/wiki/event_sourcing/).

Хранилище событий на одной таблице PostgreSQL 18.6, без фреймворка, чтобы механизм был виден
целиком. Заказ интернет-магазина хранится не строкой с текущим состоянием, а потоком событий
`OrderCreated`, `ItemAdded`, `ItemRemoved`, `OrderPaid`, `OrderShipped`. Состояние получается
сверткой событий по порядку версий. Уникальный индекс `(stream_id, stream_version)` даёт
оптимистичную конкурентность, триггер запрещает менять и удалять события. Асинхронный проектор
строит модель чтения по чекпойнту, снапшот сокращает свертку длинного потока, апкастер поднимает
старую версию события при чтении.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker, порт `127.0.0.1:55437`, схема из `schema.sql` при первом старте |
| `requirements.txt` | `psycopg[binary]==3.3.8` |
| `schema.sql` | журнал `events`, триггеры только на добавление, `snapshots`, `projection_checkpoints`, модель чтения `order_summary` |
| `order.py` | агрегат «заказ»: команды с инвариантами и свертка событий в состояние, без зависимостей |
| `event_store.py` | запись с ожидаемой версией, чтение потока, чтение журнала проектором (наивное и по горизонту транзакций), апкастер `ItemAdded` v1 → v2 |
| `projector.py` | асинхронный проектор `order_summary` с чекпойнтом и защитой от повторной доставки |
| `es_demo.py` | сценарии `all`, `append`, `conflict`, `projection`, `snapshot`, `upcast` |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `postgres:18.6`, Python 3.10 или новее.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python es_demo.py all
docker compose down -v
```

Сценарии пишут в одну базу и рассчитаны на чистый том: перед повторным прогоном выполните
`docker compose down -v`.
