# Провайдер ClickHouse для Airflow: загрузка без дублей

Код к статье [Провайдер ClickHouse для Airflow: загрузка без дублей](https://bigdataschool.ru/blog/news/airflow-clickhouse-provider/)
в блоге BigDataSchool.

## Файлы

- `compose.yaml` — стенд: ClickHouse 26.9.23.15 и Airflow 3.3.2 standalone, по 4 ГБ памяти на сервис.
- `Dockerfile` — образ Airflow 3.3.2 с провайдером `apache-airflow-providers-clickhousedb` и
  `airflow-clickhouse-plugin` для сравнения.
- `requirements.txt` — точные версии пакетов, которые ставятся в образ.
- `check_connection.py` — `ClickHouseHook`: проверка соединения, версия сервера, дефолты
  дедупликации и `async_insert`, `session_settings`, подпись запросов в `query_log`.
- `dags/retry_dedup.py` — DAG, где каждая загрузка падает после вставки и уходит в ретрай: без окна
  дедупликации, без токена, с `insert_deduplication_token`, с пачками и с `async_insert`.
- `dedup_stats.sql` — что DAG сделал со вставками по `system.query_log`.
- `bench_insert.py` — замер вставки 1 млн строк: `bulk_insert_rows`, airflow-clickhouse-plugin
  и построчный `insert_rows` из common-sql.
- `RUNBOOK.md` — пошаговый прогон с ожидаемым выводом.

## Окружение

Docker с Compose v2, около 8 ГБ свободной памяти. Свободные порты `127.0.0.1:8080`, `8123`, `9000`.
Python на хосте не нужен: всё запускается внутри контейнера Airflow.

## Как запустить

```bash
docker compose up -d --build --wait
docker compose exec -T airflow sh -c "cd /opt/airflow/demo && python check_connection.py"
docker compose exec -T airflow airflow dags test retry_dedup
docker compose exec -T clickhouse clickhouse-client --user airflow --password airflow --multiquery < dedup_stats.sql
docker compose exec -T airflow sh -c "cd /opt/airflow/demo && python bench_insert.py"
docker compose down -v
```

Подробности, ожидаемый вывод и разбор ошибок — в `RUNBOOK.md`.
