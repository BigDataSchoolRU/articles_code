# Каталог озера данных на DuckDB: views, DuckLake, Iceberg

Код к статье: https://bigdataschool.ru/blog/news/duckdb-lake-catalog/

Одни и те же Parquet-события в S3 описываются тремя каталогами: файлом DuckDB с одними
представлениями, DuckLake с метаданными в SQLite и Iceberg с REST-каталогом. Стенд показывает,
что каждый из них переживает при новых партициях, новой колонке, удалении и мелких дозаписях.

## Файлы

| Файл | Что делает |
|---|---|
| `compose.yaml` | стенд: SeaweedFS (S3) и iceberg-rest-fixture |
| `seaweedfs/s3.json` | ключи доступа к локальному S3 |
| `make_data.py` | синтетические события по дням в `s3://lake/raw/events/dt=.../`, по желанию с новой колонкой |
| `views_catalog.py` | `build`: файл `catalog.duckdb` из представлений в S3; `read`: подключение READ_ONLY из чистого процесса |
| `ducklake_catalog.py` | те же данные в DuckLake: снапшоты, time travel, ADD COLUMN, DELETE, два писателя |
| `iceberg_catalog.py` | те же данные в Iceberg через REST-каталог: снапшоты, time travel, дерево метаданных |
| `metadata_growth.py` | 50 дозаписей по 1000 строк в DuckLake и Iceberg, рост файлов и обслуживание |
| `requirements.txt` | duckdb, boto3, pytz |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с Compose v2, около 2,5 ГБ памяти под контейнеры, Python 3.10+. DuckDB работает в venv
на хосте, расширения `httpfs`, `ducklake` и `iceberg` он скачивает сам при первом запуске. Порты
8181 (REST-каталог) и 8333 (S3) публикуются только на 127.0.0.1.

`iceberg-rest-fixture` это тестовый REST-каталог из проекта Iceberg: он держит каталог в
SQLite в памяти и теряет его при перезапуске. Для демо этого хватает, для продакшна нет.

## Как запустить

1. `docker compose up -d --wait`
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Сценарии по порядку, команды в `RUNBOOK.md`.
4. `docker compose down -v`
