# RUNBOOK: провайдер ClickHouse для Airflow, загрузка без дублей

Пошаговый прогон демо к статье
[Провайдер ClickHouse для Airflow: загрузка без дублей](https://bigdataschool.ru/blog/news/airflow-clickhouse-provider/).

## Окружение

| Компонент | Версия |
|---|---|
| Docker Engine / Compose | 29.1 / 2.40, подойдёт любой Compose v2 |
| ClickHouse | образ `clickhouse/clickhouse-server:26.9.23.15` |
| Airflow | образ `apache/airflow:3.3.2-python3.12`, режим `standalone` |
| apache-airflow-providers-clickhousedb | 1.0.1 |
| apache-airflow-providers-common-sql | 2.3.0 |
| clickhouse-connect | 1.11.0 |
| airflow-clickhouse-plugin | 1.8.0 (тянет clickhouse-driver 0.2.11) |

Что нужно:
- около 8 ГБ свободной памяти: `mem_limit` по 4 ГБ у ClickHouse и у Airflow;
- свободные порты `127.0.0.1:8080` (UI Airflow), `8123` (HTTP ClickHouse), `9000` (native ClickHouse);
- доступ к Docker Hub и PyPI для сборки образа.

Переменные окружения выставлять не нужно. Соединения Airflow заданы в `compose.yaml`:
- `clickhouse_default` — тип `clickhouse`, HTTP 8123, им пользуется провайдер;
- `clickhouse_native` — тип `generic`, порт 9000, им пользуется airflow-clickhouse-plugin.

Все команды выполняются из папки с `compose.yaml`.

## Шаг 1. Поднять стенд

Собираем образ Airflow с провайдерами и ждём, пока оба сервиса станут healthy.

```bash
docker compose up -d --build --wait
```

Что в выводе: в конце строки `Container blog-airflow_clickhouse_provider-clickhouse-1  Healthy` и
`Container blog-airflow_clickhouse_provider-airflow-1  Healthy`.

Как понять, что шаг прошёл: `docker compose ps` показывает у обоих сервисов `(healthy)`. Первая
сборка образа занимает несколько минут, повторные берут слои из кэша.

## Шаг 2. Проверить соединение и дефолты сервера

```bash
docker compose exec -T -e AIRFLOW__LOGGING__LOGGING_LEVEL=WARNING airflow \
  sh -c "cd /opt/airflow/demo && python check_connection.py"
```

Что в выводе:

```
test_connection: (True, 'Connection successfully tested')
версия сервера: 26.9.23.15
настройки сессии:
  async_insert = '1' (changed=0)
  async_insert_deduplicate = '0' (changed=0)
  insert_deduplicate = '1' (changed=0)
  insert_deduplication_token = '' (changed=0)
  wait_for_async_insert = '1' (changed=0)
настройки MergeTree:
  non_replicated_deduplication_window = 0
  replicated_deduplication_window = 10000
max_threads с session_settings: 2
http_user_agent: apache-airflow/3.3.2 apache-airflow-providers-clickhousedb/1.0.1 clickhouse-connect/1.11.0 (...)
```

Как понять, что шаг прошёл: `test_connection` вернул `True`, а `max_threads` равен 2, то есть
`session_settings` хука дошли до сервера. Обратите внимание на `async_insert = '1'` и
`non_replicated_deduplication_window = 0`: это дефолты сервера 26.9, от них зависит следующий шаг.

## Шаг 3. Ретрай после вставки: DAG retry_dedup

DAG создаёт семь таблиц и грузит в каждую по 1000 строк. Каждая загрузка падает после успешной
вставки на первой попытке и через 5 секунд уходит в ретрай. Задача `report` считает строки.

```bash
docker compose exec -T airflow airflow dags test retry_dedup 2>&1 | grep -E "строк при|DagRun Finished"
```

Что в выводе (строки `report`):

```
events_no_window: 2000 строк при ожидаемых 1000
events_no_token: 2000 строк при ожидаемых 1000
events_token_sync: 1000 строк при ожидаемых 1000
events_token_batches: 500 строк при ожидаемых 1000
events_token_per_batch: 1000 строк при ожидаемых 1000
events_token_async: 1000 строк при ожидаемых 1000
events_token_async_dedup: 1000 строк при ожидаемых 1000
```

Как читать:
- `events_no_window` — токен есть, но у не реплицируемого MergeTree окно дедупликации 0, повтор
  задваивает строки;
- `events_no_token` — окно есть, но в строках `loaded_at = now()`, хеш блока у ретрая другой;
- `events_token_sync` — окно и `insert_deduplication_token`, повтор отброшен;
- `events_token_batches` — `bulk_insert_rows(batch_size=500)` шлёт обе пачки с одним токеном
  сессии, вторая пачка отброшена как дубль первой ещё на первой попытке;
- `events_token_per_batch` — свой токен у каждой пачки через `get_client().insert(settings=...)`;
- `events_token_async`, `events_token_async_dedup` — то же с `async_insert=1`, дубль отброшен при
  сбросе буфера.

Как понять, что шаг прошёл: в конце `DagRun Finished ... state=success`, а цифры совпадают с
таблицей выше.

## Шаг 4. Что DAG сделал со вставками

```bash
docker compose exec -T clickhouse clickhouse-client --user airflow --password airflow \
  --multiquery < dedup_stats.sql
```

Что в выводе: у каждой таблицы `sent_rows = 2000` (две попытки по 1000 строк), у
`events_token_batches` четыре вставки, у таблиц `*_async` ненулевой `async_inserts`, во втором
запросе `duplicated_blocks_total` больше нуля.

Как понять, что шаг прошёл: клиент Airflow отправил по 2000 строк в каждую таблицу, а осталось в
них столько, сколько показал шаг 3. Разницу отбросил сервер.

## Шаг 5. Замер путей вставки

```bash
docker compose exec -T -e AIRFLOW__LOGGING__LOGGING_LEVEL=WARNING airflow \
  sh -c "cd /opt/airflow/demo && python bench_insert.py"
```

Что в выводе: таблица из семи строк с медианой времени и строками в секунду. Пакетные пути
меряются на 1 млн строк три раза, построчный `insert_rows` на 2000 строк один раз. Скрипт идёт
около трёх-четырёх минут, из них две минуты занимает `insert_rows` при `async_insert=1`.

Как понять, что шаг прошёл: нет `AssertionError`, то есть после каждого прогона в таблице ровно
столько строк, сколько отправлено. Абсолютные цифры зависят от машины, порядок путей должен
сохраниться.

## Шаг 6. Убрать стенд

```bash
docker compose down -v
```

Что в выводе: `Removed` у обоих контейнеров, сети и тома `ch_data`.

Как понять, что шаг прошёл: `docker compose ps -a` пустой.

## Если не так

- **`up --wait` падает на airflow с `unhealthy`.** Airflow standalone при первом старте мигрирует
  базу метаданных, это до минуты. Посмотрите `docker compose logs airflow | tail -50`, затем
  повторите `docker compose up -d --wait`.
- **`Bind for 127.0.0.1:8080 failed: port is already allocated`.** Порт занят другим сервисом.
  Поменяйте левую часть в `ports` у `compose.yaml`, например `127.0.0.1:18080:8080`.
- **`python: can't open file '/opt/airflow/check_connection.py'`.** Скрипт запущен не из
  `/opt/airflow/demo`. Код примонтирован туда, рабочий каталог контейнера `/opt/airflow`.
- **`The conn_id clickhouse_default isn't defined`.** Контейнер собран из старого `compose.yaml`
  без переменных `AIRFLOW_CONN_*`. Пересоздайте его: `docker compose up -d --force-recreate airflow`.
- **В шаге 3 у `events_token_sync` 2000 строк.** Таблица создана без
  `non_replicated_deduplication_window` или токен меняется между попытками. Проверьте, что в токене
  нет `try_number` и времени.
- **`insert_rows` в шаге 5 идёт очень долго.** Это ожидаемо: при `async_insert=1` и
  `wait_for_async_insert=1` каждая строка ждёт сброса буфера. Для скорости уменьшите `N_ROWWISE`.
- **В шаге 5 предупреждение `The airflow.hooks.base.BaseHook attribute is deprecated`.** Его
  печатает airflow-clickhouse-plugin 1.8.0 на Airflow 3: плагин импортирует хук по старому пути.
  На результат не влияет.
- **Скрипт замера падает с `MemoryError` или контейнер перезапускается.** Миллион кортежей в Python
  плюс Airflow не помещаются в лимит. Уменьшите `N` в `bench_insert.py` или поднимите `mem_limit`.
