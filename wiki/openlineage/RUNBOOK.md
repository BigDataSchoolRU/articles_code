# RUNBOOK: OpenLineage на Python и Apache Spark

Стенд для статьи https://bigdataschool.ru/wiki/openlineage/ . Поднимается за несколько минут,
внешних сервисов и ключей не нужно: потребитель событий это свой сборщик на стандартной
библиотеке Python.

## Окружение

| Компонент | Версия | Откуда |
|---|---|---|
| Python | 3.12 | системный |
| openlineage-python | 1.55.0 | PyPI, `requirements.txt` |
| openlineage-spark_2.13 | 1.55.0 | Maven Central, jar 43.7 МБ |
| Apache Spark | 4.0.4, Scala 2.13, Java 17 | образ `apache/spark:4.0.4-scala2.13-java17-python3-ubuntu`, 2.1 ГБ |
| Спецификация OpenLineage | 2-0-2 | поле `schemaURL` каждого события |
| Docker / Compose | 29.1 / 2.40 | любой Docker с Compose v2 |

Нужно: Linux (контейнер Spark работает в сети хоста, `network_mode: host`), свободный порт
5000 на `127.0.0.1`, около 3 ГБ свободной памяти. Ниже `/path/to/openlineage` это ваша папка
проекта, в выводе будет ваш абсолютный путь.

## Шаг 1. Окружение Python и jar listener'а

```bash
cd /path/to/openlineage
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip list | grep -i openlineage
mkdir -p jars
curl -sSfL -o jars/openlineage-spark_2.13-1.55.0.jar \
  https://repo1.maven.org/maven2/io/openlineage/openlineage-spark_2.13/1.55.0/openlineage-spark_2.13-1.55.0.jar
sha256sum jars/openlineage-spark_2.13-1.55.0.jar
docker pull apache/spark:4.0.4-scala2.13-java17-python3-ubuntu
```

Ожидаемо: `openlineage-python 1.55.0`, размер jar 43676453 байт, sha256
`da278ffadc9c43b063169d3991890a97924d5bb1d21954c65e2fe785dd373d70`. Клиент тянет `requests`,
`httpx2`, `attrs`, `PyYAML`, venv около 32 МБ.

## Шаг 2. Сборщик событий

В отдельном терминале:

```bash
.venv/bin/python collector.py serve --port 5000
```

```
сборщик слушает http://127.0.0.1:5000/api/v1/lineage, пишет в /path/to/openlineage/events.jsonl
```

Путь `/api/v1/lineage` выбран не случайно: это путь HTTP-транспорта клиента по умолчанию и
путь приёма событий в Marquez. Сборщик дописывает каждое событие строкой в `events.jsonl` и
печатает строку `принято <тип> <задание>`.

## Шаг 3. Python-конвейер сообщает о себе

```bash
.venv/bin/python emit_pipeline.py
```

```
load_orders_clean
  -> START    bds_demo/load_orders_clean run=…bf9d6e9aba49
  записано строк: 8 (оплаченные из 10)
  -> COMPLETE bds_demo/load_orders_clean run=…bf9d6e9aba49
build_daily_revenue (колонка суммы: amount_rub)
  -> START    bds_demo/build_daily_revenue run=…1358bb478472
  задание упало: OperationalError: no such column: amount_rub
  -> FAIL     bds_demo/build_daily_revenue run=…1358bb478472
build_daily_revenue (колонка суммы: amount)
  -> START    bds_demo/build_daily_revenue run=…fb304bcffd26
  -> COMPLETE bds_demo/build_daily_revenue run=…fb304bcffd26
   ('2026-11-10', 3, 2430.5)
   ('2026-11-11', 3, 3849.9)
   ('2026-11-12', 2, 2185.25)
```

Хвосты `runId` у вас будут свои. Как понять, что шаг прошёл: в терминале сборщика шесть строк
`принято`, рядом появился `emitted.jsonl` с теми же шестью событиями (второй транспорт
составного), в `warehouse/` два файла SQLite. Весь конвейер вместе с отправкой занимает
меньше секунды.

Посмотреть одно событие целиком:

```bash
.venv/bin/python collector.py show build_daily_revenue FAIL
.venv/bin/python collector.py show build_daily_revenue COMPLETE
```

У FAIL в `run.facets.errorMessage` лежат текст ошибки и трассировка, у COMPLETE в
`outputs[0].facets` фасеты `schema` и `columnLineage`, в `job.facets.sql` текст запроса.
`schemaURL` события `https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent`.

## Шаг 4. Spark-задание без единой строки OpenLineage

```bash
docker compose run --rm spark
```

```
26/11/12 19:58:39 INFO EventEmitter: Emitting lineage completed successfully with run id: 01a1d157-407b-...
...
+--------+------+-------+--------------+
|customer|orders|revenue|last_order_day|
+--------+------+-------+--------------+
|alice   |3     |2290.00|2026-11-12    |
|bob     |2     |1950.50|2026-11-11    |
|carol   |1     |2250.00|2026-11-11    |
|dave    |2     |1975.15|2026-11-12    |
+--------+------+-------+--------------+
```

Listener подключается только флагами `spark-submit` в `compose.yaml`:
`--jars jars/openlineage-spark_2.13-1.55.0.jar`,
`spark.extraListeners=io.openlineage.spark.agent.OpenLineageSparkListener`,
`spark.openlineage.transport.type=http`, `spark.openlineage.transport.url=http://127.0.0.1:5000`,
`spark.openlineage.namespace=bds_demo`. В терминале сборщика появляются 12 событий: START и
COMPLETE приложения `customer_revenue` и отдельные задания на каждое действие Spark, у которых
в фасете `parent` указано приложение. Первый запуск на нашем стенде шёл 82 с (холодный кэш образа и JVM),
повторные 15-20 с.

## Шаг 5. Тот же файл под другим именем

```bash
.venv/bin/python emit_pipeline.py broken
```

Задание `orders_report` читает тот же `data/orders.csv`, но называет его относительным путём.

## Шаг 6. Граф из событий обоих производителей

```bash
.venv/bin/python collector.py graph
```

Ключевые строки:

```
событий в журнале: 20
по типам: {'COMPLETE': 6, 'FAIL': 1, 'RUNNING': 5, 'START': 8}
...
компонент связности графа: 2
  [1] датасетов 4, заданий 5
      file::/path/to/openlineage/data/orders.csv
      file::/tmp/lake/customer_revenue
      sqlite://warehouse::mart.daily_revenue
      sqlite://warehouse::staging.orders_clean
  [2] датасетов 2, заданий 1
      file::/path/to/openlineage/report.txt
      file::data/orders.csv

колоночный lineage (поле выхода <- поля входов):
  file::/tmp/lake/customer_revenue
    customer   <- orders.csv.customer [DIRECT:IDENTITY]
    orders     <- orders.csv.order_id [DIRECT:AGGREGATION]
    revenue    <- orders.csv.amount [DIRECT:AGGREGATION]
    last_order_day <- orders.csv.order_ts [DIRECT:AGGREGATION]
    (весь датасет) <- orders.csv.status [INDIRECT:FILTER]
    (весь датасет) <- orders.csv.customer [INDIRECT:GROUP_BY]
```

Компонента 1: Python и Spark назвали CSV одинаково (`namespace` `file`, абсолютный путь), и
граф склеился по этому узлу. Компонента 2: тот же файл под именем `data/orders.csv` стал
отдельным узлом, связь с остальным графом потеряна. Колоночный lineage Spark построил сам из
плана запроса, у Python-заданий он передан вручную.

## Шаг 7. Что будет, если потребитель недоступен

Остановите сборщик (Ctrl+C) и повторите конвейер с замером:

```bash
time .venv/bin/python emit_pipeline.py
```

Ожидаемо: код возврата 0 и те же три строки результата, шесть предупреждений
`Transport <HttpTransport(name=collector, ...)> failed to emit event ... Connection refused`,
файловый транспорт дописал шесть событий в `emitted.jsonl`. Время вырастает с 0.65 с до
54.7 с: HTTP-транспорт синхронный и по умолчанию повторяет запрос до 5 раз с
`backoff_factor` 0.3, около 9 с на каждое событие.

## Если не так

- **`Connection refused` при шаге 3 или 4.** Сборщик не запущен или занят порт 5000. Проверьте
  `ss -ltn | grep 5000`, при другом порте поменяйте `url` в `openlineage.yml` и
  `spark.openlineage.transport.url` в `compose.yaml`.
- **Spark не достучался до сборщика на macOS или Windows.** `network_mode: host` работает только
  в Linux. В Docker Desktop замените адрес на `http://host.docker.internal:5000` и уберите
  `network_mode`, а сборщик запустите как `collector.py serve --host 0.0.0.0`.
- **Граф распался на две компоненты и без шага 5.** Папка проекта смонтирована в контейнер по
  другому пути. Compose подставляет `${PWD}`: запускайте `docker compose` из папки проекта,
  тогда путь к CSV внутри контейнера совпадает с путём на хосте.
- **Длинное предупреждение `illegal reflective access` от `SparkOpenLineageExtensionVisitorWrapper`.**
  Безвредно для этого стенда: оно про коннекторы, загруженные другим загрузчиком классов. Его
  прячет `log4j2.properties`; если вы подключаете listener без этого файла, оно будет в консоли.
- **Задание `customer_revenue.map_partitions_parallel_collection` только со START.** Это
  служебное действие Spark при чтении результата обратно для `show()`, COMPLETE для него
  listener не прислал. На граф не
  влияет, сборщик считает задание по его входам.
- **Задание тормозит при упавшем потребителе.** Это шаг 7: уменьшите `retry` и `timeout` в
  секции `http` файла `openlineage.yml` или отправляйте события асинхронно.
