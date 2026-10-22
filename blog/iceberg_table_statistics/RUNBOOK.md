# RUNBOOK: статистика таблиц Iceberg на Trino и Spark

## Окружение

| Компонент | Версия |
|---|---|
| Trino | 484 (`trinodb/trino:484`) |
| Spark | 4.0.4, Scala 2.13, Java 17 |
| Apache Iceberg | 1.10.1: `iceberg-spark-runtime-4.0_2.13`, `iceberg-aws-bundle`, `apache/iceberg-rest-fixture` |
| S3 | SeaweedFS 4.48 (`chrislusf/seaweedfs:4.48`) |
| Python | 3.12, пакеты из `requirements.txt` |

Нужно: Docker с Compose v2, около 9 ГБ памяти под контейнеры, свободные порты 8080, 8181,
8333 на 127.0.0.1, доступ в интернет для образов и jar из Maven Central. Переменные окружения
не нужны: ключи локального S3 заданы в `compose.yaml` и `seaweedfs/s3.json`.

Все команды выполняются из папки с кодом.

## Шаг 1. Поднять стенд

```bash
docker compose up -d --build --wait
```

Что в выводе: `create_bucket` в состоянии `Exited`, остальные `Healthy` или `Started`.

Как понять, что прошло: `docker compose logs create_bucket` печатает
`bucket warehouse ready`, а `curl -s 127.0.0.1:8181/v1/config` отвечает JSON.

## Шаг 2. Python-клиенты

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Как понять, что прошло: `.venv/bin/python -c "import trino, boto3"` без ошибок.

## Шаг 3. Таблицы без NDV

```bash
docker compose exec -T trino trino --output-format ALIGNED --file /demo/01_load_without_ndv.sql
```

Что в выводе: четыре строки `CREATE TABLE: N rows` (25, 150000, 1500000, 6001215) и
SHOW STATS по `orders`.

Как понять, что прошло: в SHOW STATS колонка `distinct_values_count` везде `NULL`, а
`low_value`, `high_value` и `nulls_fraction` заполнены, в итоговой строке `row_count` 1500000.

## Шаг 4. План до ANALYZE

```bash
.venv/bin/python join_plan.py "без NDV"
```

Что в выводе: узлы `InnerJoin` с `Estimates: {rows: ? (?)}` и время трёх запусков.

Как понять, что прошло: оценки строк у join неизвестны (`?`), join идут в порядке запроса:
`lineitem`, затем `orders`, `customer`, `nation`.

## Шаг 5. ANALYZE

```bash
docker compose exec -T trino trino --output-format ALIGNED --file /demo/02_analyze.sql
```

Что в выводе: четыре `ANALYZE` с пустой таблицей `rows NULL`, SHOW STATS по `orders` и точные значения
`exact_custkey 99996`, `exact_clerk 1000`.

Как понять, что прошло: `distinct_values_count` заполнен у всех колонок, у `custkey` он
близок к 99996, но не равен ему: это оценка по theta sketch.

## Шаг 6. Где лежит NDV

```bash
.venv/bin/python inspect_metadata.py orders
```

Что в выводе: один файл в разделе `statistics` с тем же `snapshot-id`, что у текущего
снапшота, девять блобов `apache-datasketches-theta-v1`, магия `PFA1` в начале и конце файла и
`created-by: Trino version 484` в футере.

Как понять, что прошло: значения `ndv` в блобах совпадают с SHOW STATS из шага 5.

## Шаг 7. План после ANALYZE

```bash
.venv/bin/python join_plan.py "после ANALYZE"
```

Что в выводе: у join появились оценки строк, порядок join другой.

Как понять, что прошло: в оценках нет `?`, `customer`, `orders` и `nation` соединяются
до `lineitem`.

## Шаг 8. Удалить NDV от Trino

```bash
docker compose exec -T trino trino --output-format ALIGNED --file /demo/03_drop_extended_stats.sql
.venv/bin/python join_plan.py "после drop_extended_stats"
```

Что в выводе: четыре строки с `removed_statistics_count`, SHOW STATS без NDV, план снова с `?`.

## Шаг 9. NDV от Spark

```bash
docker compose exec -T spark /opt/spark/bin/spark-submit --driver-memory 2g /demo/04_spark_compute_stats.py
```

Что в выводе: пустой словарь статистики до расчёта, по строке на каждую таблицу с именем
`.stats` файла, `distinctCount` и `nullCount` для `orderkey`, `custkey`, `orderdate` после
расчёта и строки логического плана с `rowCount`.

Как понять, что прошло: после расчёта у трёх колонок есть `distinctCount`, до расчёта словарь
пуст. `nullCount` остаётся `None`: Iceberg отдаёт Spark только NDV, а оценки строк у join
в плане Spark остаются завышенными.

## Шаг 10. Trino читает Puffin от Spark

```bash
docker compose exec -T trino trino --output-format ALIGNED --file /demo/05_show_stats.sql
.venv/bin/python inspect_metadata.py orders
.venv/bin/python join_plan.py "NDV от Spark"
```

Что в выводе: NDV только у `orderkey`, `custkey`, `orderdate`, в футере Puffin `created-by`
от Spark, план с оценками, как в шаге 7.

Как понять, что прошло: Trino строит план с оценками строк, хотя сам статистику не считал.

## Шаг 11. Убрать стенд

```bash
docker compose down -v
```

## Если не так

- `create_bucket` не завершается: SeaweedFS ещё не поднял master. Посмотрите
  `docker compose logs seaweedfs`, обычно хватает подождать минуту.
- Trino не видит схему `iceberg.tpch` после перезапуска: `iceberg-rest-fixture` хранит каталог
  в памяти. Удалите стенд с `down -v` и пройдите с шага 1.
- `ANALYZE` или CTAS падает по памяти: Trino нужно 4 ГБ, проверьте лимиты Docker Desktop.
- В шаге 3 `distinct_values_count` уже заполнен: в сессии не сработал
  `SET SESSION iceberg.collect_extended_statistics_on_write = false`. Запускайте файл
  целиком через `--file`, а не по строкам в разных сессиях.
- `spark-submit` не находит каталог `iceberg`: образ собран без jar Iceberg. Пересоберите
  `docker compose build --no-cache spark`.
- Цифры времени в `join_plan.py` отличаются от статьи: они зависят от машины, сравнивайте
  планы и оценки строк, а не миллисекунды.
