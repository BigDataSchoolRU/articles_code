# Transactional outbox

Код к статье [Transactional outbox](https://bigdataschool.ru/wiki/transactional_outbox/).

Сервис заказов интернет-магазина пишет заказ и событие `OrderCreated` в одну локальную транзакцию
PostgreSQL: заказ в таблицу `orders`, событие строкой в таблицу `outbox`. Доставкой в Kafka занимается
отдельный ретранслятор. В демо их два: polling publisher на Python, который опрашивает таблицу через
`FOR UPDATE SKIP LOCKED`, и Debezium PostgreSQL connector с Outbox Event Router, который читает WAL.
Сервис лояльности начисляет баллы за заказы и отсекает повторы через таблицу `inbox`. Для сравнения
показана двойная запись без outbox и запись события прямо в WAL через `pg_logical_emit_message`.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 с `wal_level=logical` на `127.0.0.1:55438`, Kafka 4.3.2 в режиме KRaft на `127.0.0.1:59092`, Debezium Connect 3.7.0.Final на `127.0.0.1:58083` |
| `requirements.txt` | `psycopg[binary]==3.3.8`, `confluent-kafka==2.16.1` |
| `schema.sql` | `orders`, `outbox` с колонками по умолчанию Debezium, `loyalty.points` и `loyalty.inbox` |
| `connector.json` | PostgreSQL connector на `pgoutput` с Outbox Event Router SMT |
| `relay.py` | polling publisher: пачка через `SKIP LOCKED`, отправка, подтверждение брокера, отметка `published_at` |
| `consumer.py` | наивный консьюмер и консьюмер с `inbox` в одной транзакции с эффектом |
| `outbox_demo.py` | сценарии `all`, `dual_write`, `polling`, `duplicate`, `emit_message`, `cdc` |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, Python 3.10 или новее. Три контейнера занимают в работе около 1 ГБ памяти
(лимиты в compose 1, 1 и 1.5 ГБ), образы около 4 ГБ диска.
Образы `postgres:18.6`, `apache/kafka:4.3.2`, `quay.io/debezium/connect:3.7.0.Final`.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python outbox_demo.py all
docker compose down -v
```

Сценарии пишут в одну базу и один брокер и рассчитаны на чистые тома: перед повторным прогоном
выполните `docker compose down -v`.
