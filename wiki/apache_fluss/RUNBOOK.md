# RUNBOOK: таблица с первичным ключом и Arrow-лог в Apache Fluss 1.0

Пошаговый прогон демо к статье [Apache Fluss](https://bigdataschool.ru/wiki/apache_fluss/).
На каждом шаге: что делаем, команда, что должно быть в выводе и как понять, что шаг прошёл.
Ожидаемый вывод снят на прогоне 2026-11-14. Времена и порты на вашей машине будут другими. Офсеты,
события changelog, число строк и батчей совпадут, потому что данные генерируются детерминированно.

## Окружение

| Что | Версия на прогоне | Минимум |
|---|---|---|
| ОС | Ubuntu 24.04.4 LTS, x86_64 (4 vCPU, 15.7 ГБ RAM) | Linux или macOS |
| Apache Fluss | 1.0.0, бинарный дистрибутив `fluss-1.0.0-bin.tgz` | |
| Java | Temurin 17.0.19 | JDK 17: `bin/config.sh` дистрибутива проверяет версию при старте |
| Docker / Compose | 29.1.3 / 2.40.3, только для варианта Б | Compose v2 с `up --wait`, Linux (сеть хоста) |
| Python | 3.12.3 | 3.9 (требование `pyfluss`) |
| pyfluss | 1.0.0, с ним pyarrow 26.0.1, pandas 3.1.1, numpy 2.5.4 | |

Ресурсы: кластер из трёх JVM в работе занимает около 400 МиБ памяти. Venv с `pyfluss` занимает около
370 МБ, распакованные `lib/ bin/ conf/` около 86 МБ. **Диск должен быть занят меньше чем на 85%**:
выше этого порога TabletServer отклоняет запись, подробности в разделе «Если не так».

Порты: ZooKeeper `2181`, CoordinatorServer `9123`, TabletServer берёт случайный свободный порт и сообщает
его клиенту через метаданные кластера.

## Шаг 1. Дистрибутив

```bash
curl -sL https://dlcdn.apache.org/fluss/fluss-1.0.0/fluss-1.0.0-bin.tgz \
  | tar xzf - fluss-1.0.0/lib fluss-1.0.0/bin fluss-1.0.0/conf
ls fluss-1.0.0/lib
```

Архив весит 522 МБ. Больше половины в нём занимают плагины Lakehouse и файловых систем (`plugins/lance`,
`paimon`, `iceberg`, `s3`, `hdfs` и другие), а для демо они не нужны. Поэтому из потока распаковываются
только три каталога.

Ожидаем в `lib/` пять jar-файлов: `fluss-server-1.0.0.jar` (82 МБ) и четыре файла log4j.

## Шаг 2. Кластер

Конфигурация одна для обоих вариантов, `server.yaml` в папке демо. Это `conf/server.yaml` из дистрибутива,
к которому добавлены лимиты памяти JVM (`env.java.opts.all: -Xmx512m`, `zookeeper.heap.mb: 128`).

**Вариант А, JDK 17 установлен локально:**

```bash
cp server.yaml fluss-1.0.0/conf/server.yaml
./fluss-1.0.0/bin/local-cluster.sh start
```

**Вариант Б, без JDK, Docker на Linux:**

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d --wait
```

Внутри контейнера тот же `bin/local-cluster.sh`. Образ по умолчанию `eclipse-temurin:17-jre`, другой
образ с JDK 17 задаётся переменной `JAVA_IMAGE`. Контейнер работает в сети хоста, потому что порт
TabletServer случайный и пробросить его заранее нельзя.

Ожидаем: `Starting cluster.` (вариант А) или `Container apache-fluss-local  Healthy` (вариант Б).
Кластер поднимается за 4-10 с. В `fluss-1.0.0/log/` появляются три пары `.log`/`.out`: zookeeper,
coordinator-server и tablet-server.

## Шаг 3. Окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import fluss, pyarrow; print(fluss.__version__, pyarrow.__version__)"
```

Ожидаем `1.0.0` и версию pyarrow. `pyfluss` это Python-обёртка над Rust-клиентом Fluss, JVM ему не нужна.

## Шаг 4. Таблица с первичным ключом

```bash
.venv/bin/python pk_table_demo.py
```

Скрипт ждёт, пока зарегистрируется TabletServer, создаёт таблицу `shop.orders` с ключом `order_id`
и одним бакетом и меняет её через upsert, partial update и delete. После каждого шага он читает строку
lookup по ключу, затем замеряет задержку lookup и читает changelog таблицы с начального офсета.

```
кластер: CoordinatorServer 127.0.0.1:9123, TabletServer 127.0.0.1:41061
таблица shop.orders: первичный ключ ['order_id'], бакетов 1, has_primary_key=True
  table.kv.format-version = 2
  table.kv.value-layout-version = 1
  table.replication.factor = 1

--- шаг 1: три вставки
lookup 2: 2 boris  created     75.50

--- шаг 2: upsert по существующему ключу 2 (status -> paid)
lookup 2: 2 boris  paid        75.50

--- шаг 3: повторный upsert той же строки для ключа 2

--- шаг 4: partial update ключа 3, только amount
lookup 3: 3 vera   created    290.00

--- шаг 5: delete ключа 1
lookup 1: None (ключа нет)
lookup 2: 2 boris  paid        75.50
lookup 3: 3 vera   created    290.00
```

Lookup видит каждое изменение сразу после подтверждения записи. Частичное обновление поменяло только
`amount`, `status` остался прежним.

```
50 последовательных lookup через один Lookuper: 102.8 мс на запрос
512 lookup параллельно через   1 Lookuper:   52504 мс всего, найдено 512
512 lookup параллельно через  32 Lookuper:    1644 мс всего, найдено 512
512 lookup параллельно через 128 Lookuper:      80 мс всего, найдено 512
```

Около 100 мс на запрос это не скорость сервера. Клиент собирает ключи в батч до 128 штук и ждёт его
заполнения до 100 мс. Один `Lookuper` в `pyfluss` 1.0.0 отправляет запросы строго по одному, поэтому
каждый ждёт таймаут целиком, даже если вызовы идут параллельно. Когда одновременно запросы отправляют
128 и больше Lookuper, батч заполняется сразу и уходит без ожидания.

```
--- changelog таблицы orders, бакет 0, офсеты 0..9
offset  0  +I  1 anna   created    120.00
offset  1  +I  2 boris  created     75.50
offset  2  +I  3 vera   created    310.00
offset  3  -U  2 boris  created     75.50
offset  4  +U  2 boris  paid        75.50
offset  5  -U  2 boris  paid        75.50
offset  6  +U  2 boris  paid        75.50
offset  7  -U  3 vera   created    310.00
offset  8  +U  3 vera   created    290.00
offset  9  -D  1 anna   created    120.00
событий в changelog: 10
```

Сервер сам вывел changelog из состояния ключа: для обновления пишется пара `-U` (старая строка) и `+U`
(новая), для удаления `-D` с последним значением строки. Повторный upsert той же строки тоже дал пару
`-U`/`+U` (офсеты 5 и 6): одинаковые значения сервер не отбрасывает. Partial update попал в changelog
полной строкой.

## Шаг 5. Лог-таблица, проекция и фильтр

```bash
.venv/bin/python log_table_projection.py
```

Скрипт создаёт две одинаковые лог-таблицы на 12 колонок: `shop.clicks` с настройками по умолчанию и
`shop.clicks_stats` со свойством `table.statistics.columns = event_day`. В каждую пишет по 200 тыс.
кликов за 10 дней, каждый день отдельным батчем. Байты по сети меряются счётчиком интерфейса `lo` в
`/proc/net/dev`, поэтому на macOS эта колонка не покажет осмысленных чисел.

```
таблица shop.clicks: колонок 12, первичный ключ нет, бакетов 1, свойства {'table.replication.factor': '1'}
  записано 200000 строк за 10 дней, 0.4 с, офсеты 0..199999
таблица shop.clicks_stats: колонок 12, первичный ключ нет, бакетов 1, свойства {'table.statistics.columns': 'event_day', 'table.replication.factor': '1'}
  записано 200000 строк за 10 дней, 0.3 с, офсеты 0..199999

--- все 12 колонок:      200000 строк, 10 батчей, по сети  11.25 МиБ, 0.17 с
--- проекция 2 колонок:  200000 строк, 10 батчей, по сети   0.46 МиБ, 0.06 с  (4.1% от полного чтения)
--- фильтр event_day=5, clicks      : 200000 строк, 10 батчей, по сети  0.46 МиБ, дни в ответе [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
--- фильтр event_day=5, clicks_stats: 20000 строк, 1 батчей, по сети  0.05 МиБ, дни в ответе [5]
```

Проекция двух колонок из двенадцати сократила трафик до 4.1%: лог хранится в колоночном формате Arrow,
и сервер отдаёт только запрошенные колонки. Фильтр на таблице по умолчанию не отбросил ни одного батча,
потому что колоночная статистика не собирается, пока её не включили свойством `table.statistics.columns`.
На `clicks_stats` сервер отдал один батч из десяти. Отбор идёт по батчам целиком, поэтому в рабочем коде
предикат повторяют на клиенте.

## Шаг 6. Остановка

```bash
./fluss-1.0.0/bin/local-cluster.sh stop     # вариант А
docker compose down                         # вариант Б
```

В варианте Б данные кластера лежат в `/tmp` контейнера и удаляются вместе с ним. В варианте А они
остаются в `/tmp/fluss-data` и `/tmp/zookeeper` на хосте.

## Если не так

- **`flush()` или `wait()` висит, исключения нет.** Проверьте заполнение диска. При заполнении на 85%
  и выше TabletServer перестаёт принимать запись и снова принимает её, только когда заполнение
  опустится до 80%. Клиенту ошибка не приходит: запись просто не подтверждается. В логе TabletServer
  при этом есть строка
  `WARN ... DiskUsageMonitor ... disk usage reached 99.62% (limit 85.00%); rejecting writes until usage reaches or drops below 80.00%`.
  Освободите место. Для стенда, где место освободить нельзя, порог меняется ключом
  `server.data-disk.write-limit-ratio` в `server.yaml`: значение `1.0` отключает защиту.
- **`FlussError(code=65): This coordinator server is not the current leader` сразу после старта.**
  Порт 9123 открывается раньше, чем CoordinatorServer становится лидером, поэтому healthcheck по порту
  в `docker-compose.yml` не гарантирует готовность. Скрипты демо переподключаются раз в секунду до 90 с.
  В своём коде делайте так же или ждите, пока `get_server_nodes()` вернёт TabletServer.
- **Скрипт пишет `кластер не готов за 90 с`.** TabletServer не зарегистрировался. Посмотрите
  `fluss-1.0.0/log/*tablet-server*.log` и `*.out`. Частые причины: занят порт 2181 или 9123, Java
  старше 17.
- **Lookup идёт по 100 мс.** Это ожидание батча на клиенте, а не задержка сервера, см. шаг 4.
  В `pyfluss` 1.0.0 таймаут не настраивается: `Config({"client.lookup.batch-timeout": ...})` падает с
  `FlussError: Unknown property`.
- **Фильтр возвращает все батчи.** У таблицы не включена статистика. Задайте
  `properties={"table.statistics.columns": "<колонки>"}` в `TableDescriptor` при создании таблицы.
- **Docker не на Linux: клиент не подключается к TabletServer.** Вариант Б опирается на сеть хоста
  (`network_mode: host`) и проверен только на Linux. Порт TabletServer случайный, поэтому пробросить его
  заранее нельзя. На других ОС используйте вариант А с локальным JDK 17.
- **В `*.out` есть `WARNING: Unknown module: org.apache.arrow.memory.core specified to --add-opens`.**
  Это безвредно: скрипт запуска передаёт этот флаг всем JVM.
