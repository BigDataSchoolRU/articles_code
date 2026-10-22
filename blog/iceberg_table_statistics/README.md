# Статистика таблиц Iceberg: Puffin, NDV и планы Trino

Код к статье: https://bigdataschool.ru/blog/news/iceberg-table-statistics/

Стенд показывает, где Iceberg хранит NDV (number of distinct values), кто его пишет и как он
меняет план join в Trino. NDV, посчитанный Spark, читает Trino, и наоборот.

## Файлы

| Файл | Что делает |
|---|---|
| `compose.yaml` | стенд: SeaweedFS (S3), iceberg-rest-fixture, Trino 484, Spark 4.0.4 |
| `spark.Dockerfile` | образ Spark с iceberg-spark-runtime и iceberg-aws-bundle 1.10.1 |
| `log4j2.properties` | тихие логи Spark |
| `seaweedfs/s3.json` | ключи доступа к локальному S3 |
| `trino/iceberg.properties` | каталог Iceberg в Trino поверх REST и S3 |
| `01_load_without_ndv.sql` | TPC-H sf1 в Iceberg через CTAS без сбора NDV, SHOW STATS |
| `join_plan.py` | EXPLAIN join-запроса и медиана трёх запусков |
| `02_analyze.sql` | ANALYZE четырёх таблиц, SHOW STATS, сверка с точным count(DISTINCT) |
| `inspect_metadata.py` | раздел `statistics` в metadata.json и разбор футера Puffin |
| `03_drop_extended_stats.sql` | удаление NDV, который записал Trino |
| `04_spark_compute_stats.py` | `compute_table_stats` в Spark и NDV в плане Spark CBO |
| `05_show_stats.sql` | SHOW STATS в Trino по Puffin, который записал Spark |
| `requirements.txt` | Python-клиенты для `join_plan.py` и `inspect_metadata.py` |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с Compose v2, около 9 ГБ памяти под контейнеры, Python 3.12. Порты 8080 (Trino), 8181
(REST-каталог) и 8333 (S3) публикуются только на 127.0.0.1.

`iceberg-rest-fixture` это тестовый REST-каталог из проекта Iceberg: он держит каталог в
SQLite в памяти и теряет его при перезапуске. Для демо этого хватает, для продакшна нет.

## Как запустить

1. `docker compose up -d --build --wait`
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Сценарии по порядку, команды в `RUNBOOK.md`.
4. `docker compose down -v`
