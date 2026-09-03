# RUNBOOK: pg_clickhouse pushdown-демо

Поднимает ClickHouse и PostgreSQL с расширением pg_clickhouse рядом, наполняет
ClickHouse синтетическими данными и показывает, что именно PostgreSQL
проталкивает в ClickHouse, а что делает сам.

## Окружение

- Docker и Docker Compose (проверено на Docker Desktop, Compose v2/v3).
- Файлы этой папки: `docker-compose.yml`, `clickhouse_setup.sql`,
  `foreign_setup.sql`, `pushdown_demo.sql`.
- Все команды ниже выполняются из этой папки.
- Порты на хосте: `8123`, `9000` (ClickHouse), `5432` (PostgreSQL с
  pg_clickhouse). Освободите их заранее, если заняты чем-то другим.

Версии, на которых собран RUNBOOK: `clickhouse/clickhouse-server:25.8`
(фактически ClickHouse 25.8.33.6), `ghcr.io/clickhouse/pg_clickhouse:18`
(PostgreSQL 18.4 со встроенным расширением pg_clickhouse v0.3.x).

## Шаг 1. Поднять стенд

```bash
docker compose up -d
```

Что должно быть в выводе: два контейнера, `Started`. Дождитесь, пока оба
станут `healthy`:

```bash
docker compose ps
```

Как понять, что шаг прошёл: в колонке `STATUS` у обоих сервисов
`Up ... (healthy)`. Пока ClickHouse не health-checked, PostgreSQL-контейнер
не стартует вовсе — так задано зависимостью в `docker-compose.yml`.

## Шаг 2. Наполнить ClickHouse демо-данными

```bash
docker exec -i pg_clickhouse_ch clickhouse-client \
  --user default --password demo_pass --multiquery < clickhouse_setup.sql
```

Что должно быть в выводе: последняя строка — число `1000000`, это
`count()` из последнего запроса скрипта. Скрипт создаёт таблицу
`analytics.events` (1 млн строк синтетических событий) и представление
`analytics.events_uint64_safe`, которое понадобится в шаге 4.

## Шаг 3. Подключить ClickHouse как foreign server

```bash
docker exec -i pg_clickhouse_pg psql -U postgres < foreign_setup.sql
```

Что должно быть в выводе: `CREATE EXTENSION`, `CREATE SERVER`,
`CREATE USER MAPPING`, `CREATE SCHEMA`, `IMPORT FOREIGN SCHEMA`, а следом
список из двух foreign-таблиц (`events`, `events_uint64_safe`) и структура
`analytics.events` с колонками PostgreSQL-типов (`bigint`, `text`,
`numeric(10,2)`, `timestamp with time zone`).

Если на этом шаге ошибка `Authentication failed: password is incorrect` —
значит контейнер ClickHouse поднят без пароля для пользователя `default`:
без явного `CLICKHOUSE_PASSWORD` образ по умолчанию запрещает сетевой
доступ этому пользователю и пускает только с localhost, а foreign server
подключается извне контейнера. В `docker-compose.yml` пароль уже задан —
если меняете его, синхронно правьте `foreign_setup.sql`.

## Шаг 4. Посмотреть, что проталкивается, а что нет

```bash
docker exec -i pg_clickhouse_pg psql -U postgres < pushdown_demo.sql
```

Три блока в выводе:

1. **Успешный pushdown.** `EXPLAIN (VERBOSE)` показывает строку
   `Remote SQL: SELECT event_type, count(*) FROM analytics.events WHERE (...) GROUP BY event_type`
   — WHERE и агрегат целиком ушли в ClickHouse, PostgreSQL получил готовый
   результат на 3 строки.
2. **JOIN локальной и удалённой таблицы.** `EXPLAIN (VERBOSE)` показывает
   `Remote SQL: SELECT user_id FROM analytics.events` без фильтра — вся
   колонка вытягивается локально, а `Hash Join` с локальной таблицей
   `local_users` выполняется уже в PostgreSQL.
3. **Переполнение UInt64.** Первый `SELECT raw_uint64 ...` завершается
   ошибкой `value 18446744073709551615 is out of range of bigint` — так и
   задумано, это ожидаемая часть демонстрации, а не сбой. Второй запрос к
   `events_uint64_safe` (та же величина через `toString()` на стороне
   ClickHouse) возвращает строку `18446744073709551615` без ошибки.

`psql` без флага `ON_ERROR_STOP` не прерывается на этой ошибке и доходит до
конца скрипта — код возврата всё равно `0`.

## Если не так

- **`docker compose up` падает на порту 5432/8123/9000 занят** — на хосте
  уже что-то слушает эти порты (например, локальный PostgreSQL или
  ClickHouse). Смените проброс портов в `docker-compose.yml` или
  остановите конфликтующий сервис.
- **`psql: could not connect to server`** — контейнер `pg_clickhouse_pg` ещё
  не прошёл healthcheck, подождите и проверьте `docker compose ps`.
- **`relation "analytics.events" does not exist` в шаге 4** — шаг 3
  (`foreign_setup.sql`) не выполнился до конца, IMPORT FOREIGN SCHEMA не
  создал foreign-таблицы. Проверьте вывод шага 3 на ошибки подключения.
- **Хотите начать с нуля** — `docker compose down -v` удаляет контейнеры
  вместе с данными, следующий `docker compose up -d` поднимает всё заново.
