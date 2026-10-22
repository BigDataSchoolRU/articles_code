# RUNBOOK: каталог озера данных на DuckDB

## Окружение

| Компонент | Версия |
|---|---|
| DuckDB | 2.0.0 (Python), расширения `httpfs`, `ducklake` (формат DuckLake 1.1), `iceberg` |
| Iceberg REST-каталог | `apache/iceberg-rest-fixture:1.10.1` |
| S3 | SeaweedFS 4.48 (`chrislusf/seaweedfs:4.48`) |
| Python | 3.10+, пакеты из `requirements.txt` |

Нужно: Docker с Compose v2, около 2,5 ГБ памяти под контейнеры, свободные порты 8181 и 8333 на
127.0.0.1, доступ в интернет для образов, PyPI и расширений DuckDB. Переменные окружения не
нужны: ключи локального S3 заданы в `compose.yaml`, `seaweedfs/s3.json` и в самих скриптах.

Все команды выполняются из папки с кодом. Локальные файлы скрипты складывают в `work/`.

## Шаг 1. Поднять стенд

```bash
docker compose up -d --wait
```

Что в выводе: `create_bucket` в состоянии `Exited`, `seaweedfs` и `rest` в состоянии `Healthy`.

Как понять, что прошло: `docker compose logs create_bucket` печатает `bucket lake ready`, а
`curl -s 127.0.0.1:8181/v1/config` отвечает JSON.

## Шаг 2. DuckDB в venv

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Как понять, что прошло: `.venv/bin/python -c "import duckdb; print(duckdb.__version__)"`
печатает `2.0.0`.

## Шаг 3. Сырые данные

```bash
.venv/bin/python make_data.py 2026-10-01 10
```

Что в выводе: десять строк `dt=2026-10-01: 200000 строк` и далее, в конце
`всего в s3://lake/raw/events/: 10 файлов, 24.9 МБ`.

Как понять, что прошло: десять дней, по одному Parquet-файлу на день.

## Шаг 4. Каталог из представлений

```bash
.venv/bin/python views_catalog.py build
.venv/bin/python views_catalog.py read
```

Что в выводе `build`: два представления `daily` и `events`, текст `events` с `read_parquet` по
glob и строка `catalog.duckdb: 268 КБ, данные под ним: 24.9 МБ`.

Что в выводе `read`:
- `ATTACH без секрета` падает с `HTTP 403 Forbidden`;
- `ATTACH READ_ONLY по s3` проходит;
- `cat.daily` печатает десять дней по 200000 событий;
- запрос к `channel` падает с `Binder Error`, такой колонки ещё нет;
- `запись в каталог` падает с `attached in read-only mode`.

Как понять, что прошло: агрегаты посчитаны из чистого процесса, у которого есть только адрес
файла каталога и ключ к S3.

## Шаг 5. Новая партиция и новая колонка

```bash
.venv/bin/python make_data.py 2026-10-11 1
.venv/bin/python make_data.py 2026-10-12 1 --with-channel
.venv/bin/python views_catalog.py read
```

Что в выводе: в `cat.daily` двенадцать дней, `2026-10-11` и `2026-10-12` тоже по 200000. В
колонках `cat.events` по-прежнему нет `channel`, и запрос к ней снова падает с `Binder Error`.

Как понять, что прошло: новая партиция видна без пересборки каталога, а новая колонка в новых
файлах не видна. Схему `read_parquet` без `union_by_name` берёт по первому файлу.

## Шаг 6. DuckLake

```bash
.venv/bin/python ducklake_catalog.py
```

Что в выводе:
- шесть снапшотов от `schemas_created` до `tables_deleted_from`;
- `строк сейчас: 2371428`, `AT (VERSION => 1)` даёт 2000000, `AT (VERSION => 2)` даёт 2200000;
- `channel по дням`: у `2026-10-11` 0 значений, у `2026-10-12` 200000;
- `кодек Parquet по умолчанию: [('SNAPPY',)]`;
- `файлы данных: 3`, `файлов удалений: 1`;
- `work/lake.sqlite` около 156 КБ и 31 таблица;
- оба писателя: `успешно 20, ошибок 0`, в таблице по 20 строк от `A` и `B`.

Как понять, что прошло: колонка добавилась без перезаписи старых файлов, удаление легло
отдельным файлом, а два процесса записали в одну таблицу через один файл SQLite.

## Шаг 7. Iceberg через REST-каталог

```bash
.venv/bin/python iceberg_catalog.py
```

Что в выводе:
- `ADD COLUMN: да`;
- четыре снапшота: три `append` и один `delete`;
- `строк сейчас: 2371428`, на первом снапшоте 2000000;
- `REST metadata-location` с путём к `00004-...metadata.json`;
- `metadata/` около 13 файлов на 35 КБ, `data/` 4 файла около 13 МБ.

Как понять, что прошло: те же данные и те же числа строк, что в DuckLake. Каталог хранит только
указатель на metadata.json, всё дерево метаданных лежит рядом с данными в S3.

## Шаг 8. Рост метаданных после 50 дозаписей

```bash
.venv/bin/python metadata_growth.py
```

Что в выводе после 50 дозаписей:
- DuckLake: 50 Parquet-файлов в S3, SQLite около 168 КБ, 52 снапшота;
- Iceberg: 50 файлов в `data/`, около 151 файла в `metadata/` на 1,3 МБ, 50 снапшотов.

Что в выводе после обслуживания:
- DuckLake: один Parquet-файл и один снапшот;
- Iceberg: на файл и на снапшот больше, `metadata/` выросла.

Как понять, что прошло: на каждую дозапись Iceberg кладёт в S3 около трёх файлов метаданных,
DuckLake пишет только строки в SQLite. DuckLake сам склеивает файлы и удаляет старые снапшоты.
Iceberg в DuckDB умеет только перезаписать файлы данных, старые снапшоты чистит другой движок.

## Шаг 9. Убрать стенд

```bash
docker compose down -v
```

Как понять, что прошло: контейнеры и том `s3_data` удалены. Папку `work/` можно удалить руками.

## Если не так

- **`rest` в состоянии `unhealthy` на шаге 1.** JVM на слабой машине стартует дольше. Повторите
  `docker compose up -d --wait`, контейнеры уже созданные просто дождутся проверки.
- **`HTTP 403` при чтении с секретом.** Ключи в `CREATE SECRET` должны совпадать с
  `seaweedfs/s3.json`, а `ENDPOINT` указывать на `127.0.0.1:8333` без `http://`.
- **`Column type UBIGINT is not a valid Iceberg Type`.** В Iceberg нет беззнаковых целых. Функция
  `hash()` в DuckDB отдаёт `UBIGINT`, приведите её к `BIGINT`, как в `make_data.py`.
- **`Relations no longer have fetchone()` или `connection has an unfinished result`.** Это
  DuckDB 2.0: у relation нет `fetchone()`, а после `execute()` результат надо дочитать.
  Используйте `con.sql(...).fetchall()`.
- **`Required module 'pytz' failed to import`.** DuckLake отдаёт `TIMESTAMPTZ`, Python-клиенту
  DuckDB для него нужен `pytz`. Он есть в `requirements.txt`.
- **`CREATE OR REPLACE not supported in DuckDB-Iceberg`.** Для таблиц Iceberg делайте
  `DROP TABLE` и `CREATE TABLE` двумя командами. `DROP` в REST fixture файлы из S3 не удаляет,
  поэтому скрипты чистят префикс таблицы сами.
- **Расширения не скачиваются.** DuckDB тянет их с `extensions.duckdb.org`; без интернета
  поставьте их заранее через `INSTALL` на машине с доступом и скопируйте `~/.duckdb/extensions`.
