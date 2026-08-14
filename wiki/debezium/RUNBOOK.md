# RUNBOOK: Debezium Server и PostgreSQL

Пошаговый прогон демо к статье. После каждого шага указано, что должно быть в выводе.

## Окружение

- Docker 29.4.2 с запущенным демоном, свободные порты 5433, 8099 и 8100
- Python 3.12 для HTTP-приёмника событий, внешних библиотек не нужно
- Образы `postgres:18` и `quay.io/debezium/server:3.6.1.Final`, около 1 ГБ суммарно

## Шаг 1. Приёмники событий

Debezium Server отправляет события по HTTP, поэтому сначала нужен тот, кто их примет.

```bash
python3 event_sink.py events.jsonl 8099 &
python3 event_sink.py events_full.jsonl 8100 &
```

Проверка: в консоли строки вида `приёмник слушает 0.0.0.0:8099, пишет в events.jsonl`.

## Шаг 2. Postgres и Debezium Server

```bash
docker compose up -d
docker compose ps
```

Проверка: оба контейнера в статусе `Up`. Если `dbz_server` выпал в `Exited`, смотрите
`docker logs dbz_server`, там же будет причина.

## Шаг 3. Начальный снимок

Через 20-30 секунд после старта в `events.jsonl` появляются две строки.

```bash
cat events.jsonl
```

Проверка: два события с `"op":"r"` и полем `"snapshot":"first"` у первого. Это строки, которые
лежали в таблице до старта коннектора.

## Шаг 4. Поток изменений

```bash
docker exec -i dbz_pg psql -U postgres -d shopdb < workload.sql
sleep 5
tail -n 3 events.jsonl
```

Проверка: три события с `"op":"c"`, `"op":"u"` и `"op":"d"`. У события обновления блок `before`
равен `null`, у удаления в `before` заполнен только идентификатор. Так работает REPLICA IDENTITY
по умолчанию.

## Шаг 5. REPLICA IDENTITY FULL и плоский формат

```bash
docker exec -i dbz_pg psql -U postgres -d shopdb -c "ALTER TABLE orders REPLICA IDENTITY FULL;"
docker stop dbz_server
docker compose --profile full up -d server_full
sleep 30
docker exec -i dbz_pg psql -U postgres -d shopdb < workload2.sql
sleep 5
cat events_full.jsonl
```

Проверка: три плоских события без конверта, с полями `__op` и `__deleted`. Сумма приходит строкой
`"777.25"`, а не в base64.

## Шаг 6. Слоты репликации

```bash
docker exec dbz_pg psql -U postgres -d shopdb -c "select slot_name, plugin, active from pg_replication_slots;"
```

Проверка: два активных слота с плагином `pgoutput`. Слот, у которого `active` равен `f`, держит
WAL и рано или поздно заполнит диск.

## Уборка

```bash
docker compose --profile full down -v
pkill -f event_sink.py
```

## Если не так

- **Контейнер `dbz_server` падает сразу.** Обычно не хватает обязательного свойства в конфиге.
  Точную строку печатает `docker logs dbz_server` после `Caused by`.
- **События не приходят.** Проверьте, что приёмник слушает нужный порт и что в конфиге стоит
  `host.docker.internal`, а не `localhost`: для контейнера `localhost` это он сам.
- **Слот занят.** Два коннектора с одинаковым `slot.name` одновременно не работают. Имя слота
  должно быть своё у каждого.
