# RUNBOOK: Transactional outbox на PostgreSQL 18, Kafka 4.3 и Debezium 3.7

Пошаговый прогон демо к статье [Transactional outbox](https://bigdataschool.ru/wiki/transactional_outbox/).
Три контейнера (PostgreSQL, Kafka, Debezium Connect) и пять сценариев: двойная запись без outbox,
polling publisher с одним и двумя ретрансляторами, дубль после падения ретранслятора и inbox на
консьюмере, событие прямо в WAL через `pg_logical_emit_message`, тот же outbox через Debezium
Outbox Event Router.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6`, `wal_level=logical` |
| Apache Kafka | 4.3.2, образ `apache/kafka:4.3.2`, один узел KRaft |
| Debezium | 3.7.0.Final, образ `quay.io/debezium/connect:3.7.0.Final` (Kafka Connect внутри образа 4.3.1) |
| Python | 3.10 или новее, проверено на 3.12.3 |
| psycopg | 3.3.8, `psycopg[binary]` со встроенной libpq 18 |
| confluent-kafka | 2.16.1, librdkafka 2.16.0 |
| Docker | с плагином Compose |

Порты на хосте: PostgreSQL `127.0.0.1:55438` (пользователь, пароль и база `demo`/`demo`/`shop`),
Kafka `127.0.0.1:59092`, REST API Kafka Connect `127.0.0.1:58083`. Если порт занят, поменяйте его в
`docker-compose.yml` и задайте переменные окружения `PG_DSN`, `KAFKA_BOOTSTRAP` и `CONNECT_URL`.

Контейнерам нужно около 1 ГБ памяти в работе (лимиты в compose 1 ГБ, 1 ГБ и 1.5 ГБ) и около 4 ГБ
диска на образы. Весь прогон занимает около полутора минут, из них 45 секунд уходит на подъём
стенда: Kafka Connect при старте сканирует плагины. Идентификаторы событий, номера транзакций, LSN и
доли секунды у вас будут другими.

## Шаг 1. Поднять стенд и окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
docker compose exec -T pg psql -U demo -d shop -XAtc "SHOW wal_level"
curl -s http://127.0.0.1:58083/connector-plugins | grep -o 'io.debezium.connector.postgresql.PostgresConnector[^}]*'
```

Ожидаемо: три строки `Container outbox-...  Healthy`, `logical` и плагин коннектора с версией:

```
io.debezium.connector.postgresql.PostgresConnector","type":"source","version":"3.7.0.Final"
```

`schema.sql` применяется только при первом старте на пустом томе. Если таблиц нет, том остался
от прошлого запуска: `docker compose down -v` и снова `up`.

Все сценарии разом запускает `.venv/bin/python outbox_demo.py all`, по одному
`outbox_demo.py dual_write`, `polling` и так далее. Сценарии пишут в одну базу, поэтому номера
заказов ниже совпадут, только если идти по порядку на чистом томе.

## Шаг 2. Двойная запись теряет событие

```bash
.venv/bin/python outbox_demo.py dual_write
```

Сервис пишет в базу и в брокер двумя отдельными операциями. В варианте A процесс падает после
COMMIT и до отправки, в варианте B событие подтверждено брокером, а транзакция откатилась.
Ожидаемо:

```
A: заказ 1 закоммичен в БД; процесс упал до produce, событие не отправлено
B: событие OrderCreated для заказа 2 подтверждено брокером
B: соединение с БД оборвалось до COMMIT, транзакция откатилась
итог A: заказ 1 в БД: 1, событий о нём в топике: 0  -> потерянное событие
итог B: заказ 2 в БД: 0, событий о нём в топике: 1  -> фантомное событие
```

Строка librdkafka `Failed to acquire idempotence PID ... Coordinator load in progress: retrying`
на первом запуске после подъёма брокера безвредна: продюсер повторяет запрос сам.

## Шаг 3. Polling publisher с SKIP LOCKED

```bash
.venv/bin/python outbox_demo.py polling
```

Заказ и строка outbox пишутся одной транзакцией. Ретранслятор из `relay.py` забирает пачку из 10
строк через `FOR UPDATE SKIP LOCKED`, отправляет их, ждёт подтверждения брокера и отмечает
`published_at` в той же транзакции. Сначала проверяется откат: ни заказа, ни события. Затем 100
заказов с оплатами вперемешку, 200 событий, разбираются одним ретранслятором и двумя параллельно,
и последним шагом два ретранслятора с паузой первого.
Ожидаемо:

```
после отката: заказов 0 строк outbox 0

[1 ретранслятор(а)] в outbox к отправке: 200 событий (100 заказов x 2)
  relay-1: пачек 20, событий 200
  в топике polling_one.event.order: сообщений 200, уникальных id 200, повторов 0
  неотправленных строк в outbox: 0; ушло за 1.34 с (включая 1.0 с ожидания пустой таблицы)
  заказов, у которых OrderPaid в партиции раньше OrderCreated: 0 из 100

[2 ретранслятор(а)] в outbox к отправке: 200 событий (100 заказов x 2)
  relay-1: пачек 10, событий 100
  relay-2: пачек 10, событий 100
  в топике polling_two.event.order: сообщений 200, уникальных id 200, повторов 0
  неотправленных строк в outbox: 0; ушло за 1.20 с (включая 1.0 с ожидания пустой таблицы)
  заказов, у которых OrderPaid в партиции раньше OrderCreated: 1 из 100
  пример, заказ 104: OrderPaid@p0:0 -> OrderCreated@p0:2
  relay-1 захватил ['OrderCreated'] и замер до отправки
  relay-2 захватил ['OrderPaid'], строку relay-1 пропустил

[2 ретранслятора, relay-1 замер] заказ 204: OrderPaid@p0:0 -> OrderCreated@p0:1
```

`SKIP LOCKED` делит строки между ретрансляторами без дублей, но порядок событий одного заказа
больше не гарантирован: `OrderCreated` попал в пачку первого ретранслятора, `OrderPaid` в пачку
второго, и второй отправил свою раньше. Число таких заказов от запуска к запуску разное: на
пяти прогонах стенда вышло 1, 0, 3, 1 и 2 из 100. Последний шаг делает то же детерминированно:
первый ретранслятор захватывает `OrderCreated` и замирает до отправки (так выглядит пауза сборки
мусора или сети), второй через `SKIP LOCKED` берёт следующую строку, `OrderPaid` того же заказа, и
отправляет её первой. С одним ретранслятором и одним продюсером порядок внутри ключа сохраняется.

## Шаг 4. Дубль после падения ретранслятора и inbox на консьюмере

```bash
.venv/bin/python outbox_demo.py duplicate
```

Ретранслятор отправляет пять событий и падает до отметки строк, транзакция откатывается, и после
рестарта те же пять событий уходят второй раз. Наивный консьюмер начисляет баллы на каждое
сообщение. Консьюмер с inbox вставляет `id` события из заголовка в `loyalty.inbox` и начисляет баллы
в одной транзакции, а оффсет коммитит после неё. Первый проход inbox-консьюмера имитирует падение
до коммита оффсетов. Ожидаемо:

```
1-й запуск ретранслятора: ретранслятор упал после отправки и до отметки строк
  сообщений в топике: 5 | неотправленных строк в outbox: 5
2-й запуск ретранслятора: {'relay': 'relay-restart', 'batches': 1, 'events': 5}
  сообщений в топике: 10, уникальных id: 5

ожидаемые баллы: 89
наивный консьюмер: {'messages': 10, 'applied': 10} | баллов начислено: 178
inbox, 1-й проход (падает до коммита оффсетов): {'messages': 10, 'applied': 5, 'skipped': 5}
inbox, 2-й проход после рестарта: {'messages': 10, 'applied': 0, 'skipped': 10}
inbox, 3-й проход: {'messages': 0, 'applied': 0, 'skipped': 0}
  баллов начислено: 89 | строк в inbox: 5
```

## Шаг 5. Событие прямо в WAL через pg_logical_emit_message

```bash
.venv/bin/python outbox_demo.py emit_message
```

Сценарий создаёт временный слот логического декодирования с плагином `test_decoding`, пишет заказ
и транзакционное сообщение с префиксом `outbox` одной транзакцией, затем по сообщению каждого вида
в откатившейся транзакции. Ожидаемо (LSN и xid у вас другие):

```
  0/1C86EC8 xid=1242 table public.orders: INSERT: id[bigint]:210 customer[text]:'emit-1' amount[numeric]:700.00 status[text]:'created' created_at[timestamp with time zone]:'2026-11-06 15:28:12.296961+00'
  0/1C86FD0 xid=1242 message: transactional: 1 prefix: outbox, sz: 40 content:{"type": "OrderCreated", "orderId": 210}
  0/1C87128 xid=0 message: transactional: 0 prefix: outbox, sz: 65 content:{"type": "OrderCreated", "note": "rollback, transactional=False"}
строк в outbox до и после: 407 407
```

Транзакционное сообщение из откатившейся транзакции в слот не попало. Нетранзакционное попало, хотя
транзакция откатилась: для outbox годится только `transactional = true`. Строк в таблице outbox
не прибавилось.

## Шаг 6. Debezium Outbox Event Router

```bash
.venv/bin/python outbox_demo.py cdc
```

Сценарий регистрирует коннектор из `connector.json` через REST API Kafka Connect, ждёт активного
слота `outbox_slot` и делает пять заказов. У двух последних строка outbox удаляется в той же
транзакции сразу после вставки. Шестой заказ откатывается. Ожидаемо:

```
коннектор: RUNNING задачи: ['RUNNING']
слот: ('outbox_slot', 'pgoutput', True)
5 коммитов -> 5 сообщений в outbox.event.order за 0.79 с
  p1 key=211 eventType=OrderCreated id=a0f12844-... value={"amount": 1100, "orderId": 211, "customer": "cdc-0"}
  p2 key=212 eventType=OrderCreated id=23f95cd5-... value={"amount": 2600, "orderId": 212, "customer": "cdc-1"}
  p2 key=213 eventType=OrderCreated id=14b0dee2-... value={"amount": 900, "orderId": 213, "customer": "cdc-2"}
  p2 key=214 eventType=OrderCreated id=db02747f-... value={"amount": 1700, "orderId": 214, "customer": "cdc-del-0"}
  p0 key=215 eventType=OrderCreated id=8d50857f-... value={"amount": 500, "orderId": 215, "customer": "cdc-del-1"}
строк outbox у заказов cdc-del-*: 0 | событий cdc-rollback в топике: 0
```

Топик `outbox.event.order` собран из `aggregatetype`, ключ сообщения это `aggregateid`, `id` строки
лежит в заголовке, `payload` развёрнут в JSON. Удалённые в той же транзакции строки доставлены:
коннектор читает вставку из WAL, а событие DELETE маршрутизатор отбрасывает.

Затем строка outbox правится UPDATE. Нового сообщения нет, в логе Connect предупреждение:

```
после UPDATE строки outbox сообщений в топике: 5
  лог Connect: ... WARN   Postgres||lifecycle  Unexpected update message received [REDACTED] and ignored   [io.debezium.transforms.outbox.EventRouterDelegate]
```

Это поведение `table.op.invalid.behavior=warn` из `connector.json`. Логические сообщения из
`pg_logical_emit_message` коннектор отдаёт в отдельный топик `<topic.prefix>.message`, через Outbox
Event Router они не идут:

```
сообщений в shop.message: 2
  op=m txId=1253 prefix=outbox content={"type": "OrderCreated", "orderId": 217}
  op=m txId=None prefix=outbox content={"type": "OrderCreated", "note": "rollback, transactional=false"}
```

Последней строкой inbox-консьюмер читает топик Debezium тем же кодом, что и топик опросчика:
`{'messages': 5, 'applied': 5, 'skipped': 0}`.

## Шаг 7. Итог по базе

```bash
docker compose exec -T pg psql -U demo -d shop -Xc \
  "SELECT type, count(*) AS rows, count(published_at) AS published FROM outbox GROUP BY type ORDER BY type"
docker compose exec -T pg psql -U demo -d shop -Xc \
  "SELECT slot_name, plugin, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS lag FROM pg_replication_slots"
```

После всех сценариев по порядку на чистом томе ожидаемо (отставание слота у вас другое):

```
     type     | rows | published 
--------------+------+-----------
 OrderCreated |  209 |       206
 OrderPaid    |  201 |       201
(2 rows)

  slot_name  |  plugin  | active |    lag     
-------------+----------+--------+------------
 outbox_slot | pgoutput | t      | 9896 bytes
(1 row)
```

Три строки `OrderCreated` без `published_at` оставил сценарий `cdc`: их доставил Debezium, а он
отметок в таблице не ставит. Две строки `cdc-del-*` удалены в своих транзакциях. Слот держит WAL, пока коннектор его не подтвердит,
поэтому отставание слота стоит держать под мониторингом.

## Шаг 8. Уборка

```bash
docker compose down -v
```

## Если не так

- **Connect не становится healthy за пару минут.** Посмотрите `docker logs outbox-connect`. Чаще
  всего не хватает памяти: Kafka Connect с плагинами Debezium занимает около 500 МБ.
- **Коннектор в состоянии FAILED с ошибкой про `wal_level`.** База поднята без
  `wal_level=logical`, например том остался от другого compose. `docker compose down -v` и снова `up`.
- **`psql: FATAL: the database system is shutting down` сразу после `up`.** Healthcheck без
  `-h 127.0.0.1` отвечает «готов» во время initdb. В `docker-compose.yml` он уже с `-h`, проверьте,
  что вы не меняли эту строку.
- **Сценарий `cdc` выдаёт меньше пяти сообщений.** Вставки ушли в WAL раньше, чем коннектор создал
  слот. Сценарий ждёт активного слота, но при медленном старте запустите `cdc` ещё раз на чистом томе.
- **Повторный запуск даёт другие номера заказов и лишние сообщения.** Топики и таблицы остались от
  прошлого прогона. `docker compose down -v` и снова `up`.
- **`slot "outbox_slot" already exists` или растёт диск PostgreSQL.** Слот репликации держит WAL,
  пока коннектор его не подтвердит. Если коннектор больше не нужен, проверьте
  `SELECT slot_name, active FROM pg_replication_slots`, снимите лишний слот
  `SELECT pg_drop_replication_slot('outbox_slot')` или уберите стенд целиком.
