# RUNBOOK: таблица с первичным ключом, merge engine и компакция в Apache Paimon 2.1

Пошаговый прогон демо к статье [Apache Paimon](https://bigdataschool.ru/wiki/apache_paimon/).
На каждом шаге: что делаем, команда, что должно быть в выводе и как понять, что шаг прошёл.
Ожидаемый вывод снят на прогоне 2026-11-15. Времена, UUID в именах файлов и пути у вас будут другими.
Строки таблиц, номера снапшотов, бакеты, уровни и счётчики записей совпадут: данные в демо заданы явно.

## Окружение

| Что | Версия на прогоне | Минимум |
|---|---|---|
| ОС | Ubuntu 24.04.4 LTS, x86_64 (4 vCPU, 15.7 ГБ RAM) | Linux или macOS |
| Python | 3.12.3 | 3.9 |
| pypaimon | 2.1.0, с ним pyarrow 19.0.1, pandas 2.3.3, polars 1.44.2, fastavro 1.13.1 | |
| Docker / Compose | 29.1.3 / 2.40.3, только для шага 4 | Compose 2.23: встроенные `configs` с `content` |
| Spark | образ `apache/spark:4.0.4-scala2.13-java17-python3-ubuntu` (Spark 4.0.4, Temurin 17.0.19) | |
| Paimon для Spark | `paimon-spark-4.0_2.13-2.1.0.jar`, Maven Central, SHA-1 `0a0f44116ada3f08fdd2a69f74cf35a0f41f3009` | |

Ресурсы: venv занимает около 560 МБ, jar 47 МБ, образ Spark 2.1 ГБ, таблицы демо меньше 1 МБ.
Контейнеру Spark отведено 3 ГБ памяти (`mem_limit` в `compose.yaml`).

Хранилище таблиц по умолчанию лежит в папке `warehouse` рядом со скриптами. Другое место задаётся
абсолютным путём в переменной `PAIMON_WAREHOUSE`, её читают и Python-скрипты, и `compose.yaml`.

## Шаг 1. Окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip list | grep -Ei "^(pypaimon|pyarrow|pandas|polars) "
```

Ожидаем:

```
pandas             2.3.3
polars             1.44.2
pyarrow            19.0.1
pypaimon           2.1.0
```

`pypaimon` 2.1.0 требует `pyarrow` ниже 20 и `pandas` ниже 3. Если в venv уже стоят новые версии,
pip поставит версии под эти ограничения, поэтому venv для демо отдельный.

## Шаг 2. Таблица с первичным ключом

```bash
.venv/bin/python pk_table_demo.py
```

Скрипт удаляет базу `shop` в хранилище, создаёт таблицу `shop.orders` с ключом `order_id`,
`bucket = 2`, `merge-engine = deduplicate` и `changelog-producer = input` и делает два коммита.

Чтение после второго коммита: пять строк, у ключа 2 последний статус из пакета, у ключа 3 отмена.

```
--- чтение после коммита 2 (merge-on-read, последняя версия по ключу): 5 строк
 order_id customer    status  amount
        1     anna   created   120.0
        2    boris   shipped    80.0
        3     vera cancelled    45.5
        4     gleb   created   300.0
        5     dina   created    15.0
```

Потоковый читатель подключился после первого коммита и от второго получил только изменения:

```
--- потоковый читатель: изменения снапшота 2 (changelog-producer=input): 3 строк
_row_kind  order_id customer    status  amount
       +I         2    boris   shipped    80.0
       +I         5     dina   created    15.0
       +I         3     vera cancelled    45.5
```

Во втором пакете четыре записи, а в снапшоте и в changelog их три. Две записи по ключу 2 слились
ещё в буфере записи, до файла дошла последняя. Тип всех записей `+I`: `write_arrow` пишет вставки, а
`changelog-producer = input` сохраняет входные записи как есть, без пар `-U`/`+U`.

Снапшоты и файлы:

```
snapshot-1: commitKind=APPEND totalRecordCount=4 deltaRecordCount=4 changelogRecordCount=4
snapshot-2: commitKind=APPEND totalRecordCount=7 deltaRecordCount=3 changelogRecordCount=3

bucket=0 level=0 rows=3 seq=0..2 data-<uuid>-0.parquet
bucket=0 level=0 rows=2 seq=4..5 data-<uuid>-0.parquet
bucket=0: файлов 2, строк в файлах 5, raw_convertible=False
bucket=1 level=0 rows=1 seq=0..0 data-<uuid>-0.parquet
bucket=1 level=0 rows=1 seq=1..1 data-<uuid>-0.parquet
bucket=1: файлов 2, строк в файлах 2, raw_convertible=False
```

Шаг прошёл, если в таблице 5 строк, а в файлах 7 записей. Все файлы лежат на уровне 0: компакцию
`pypaimon` не делает, и при чтении версии сливаются на лету. Каталог таблицы содержит
`bucket-0/` и `bucket-1/` с файлами `data-*` и `changelog-*`, `manifest/`, `schema/schema-0` и
`snapshot/` с файлами `snapshot-1`, `snapshot-2` и `LATEST`.

## Шаг 3. Четыре merge engine

```bash
.venv/bin/python merge_engine_demo.py
```

Три коммита по ключу 1: заказ создан, затем пришёл только статус, затем только доплата. Пустое поле
означает, что в событии его не было. Ожидаем:

```
merge engine    customer  status      amount
deduplicate     None      None          25.0
partial-update  anna      paid          25.0
aggregation     anna      paid         125.0
first-row       пакетное чтение: 0 строк (видит только файлы после компакции)
                anna      created      100.0  <- потоковое чтение, уровень 0
```

`deduplicate` оставил последнюю запись целиком, вместе с пустыми полями. `partial-update` собрал строку
из непустых полей разных записей. `aggregation` сложил `amount` (`sum`), остальные поля взял по правилу
`last_non_null_value`. `first-row` хранит первую запись, но пакетное чтение таблицы с этим merge engine
пропускает файлы уровня 0, и до компакции таблица выглядит пустой. Шаг прошёл, если вывод совпал.

## Шаг 4. Компакция в Spark

Скачиваем jar и запускаем `compaction.sql` в контейнере. Папка `warehouse` к этому моменту уже создана
шагами 2 и 3, иначе Docker создаст её от root.

```bash
mkdir -p jars && curl -sSfo jars/paimon-spark-4.0_2.13-2.1.0.jar \
  https://repo1.maven.org/maven2/org/apache/paimon/paimon-spark-4.0_2.13/2.1.0/paimon-spark-4.0_2.13-2.1.0.jar
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose run --rm spark-sql
```

Первый запуск идёт около 50 секунд, большая часть уходит на старт JVM и Spark. Ожидаем (строки `Time taken`
опущены):

```
stage	bucket	level	record_count
orders до компакции	0	0	2
orders до компакции	0	0	3
orders до компакции	1	0	1
orders до компакции	1	0	1
result
true
stage	bucket	level	record_count
orders после компакции	0	5	4
orders после компакции	1	5	1
snapshot_id	commit_kind	total_record_count	delta_record_count	changelog_record_count
1	APPEND	4	4	4
2	APPEND	7	3	3
3	COMPACT	5	-2	NULL
order_id	customer	status	amount
1	anna	created	120.0
2	boris	shipped	80.0
3	vera	cancelled	45.5
4	gleb	created	300.0
5	dina	created	15.0
stage	count(1)
first-row до компакции, строк	0
result
true
stage	order_id	customer	status	amount
first-row после компакции	1	anna	created	100.0
```

Шаг прошёл, если в каждом бакете остался один файл уровня 5, в снапшоте `COMPACT` записей стало 5 вместо 7,
а таблица `first-row` после компакции отдала строку с первым статусом `created`. Данные таблицы `orders`
до и после компакции одинаковые.

Повторный запуск шагов 2-4 начинается с чистых баз `shop` и `engines`, вывод повторяется.

## Если не так

- **`first-row` показывает 0 строк и в Spark после компакции.** Проверьте, что `CALL sys.compact` вернул
  `true` для `engines.orders_first_row`. Без компакции так и должно быть.
- **Spark падает с `LoginException: invalid null input: name`.** Контейнер запущен от uid, которого нет в
  `/etc/passwd` образа. `compose.yaml` подставляет свой passwd через `configs`, для этого нужен Compose 2.23
  или новее (`docker compose version`).
- **Spark падает с `basedir must be absolute: ?/.ivy2.5.2/local`.** Та же причина: у пользователя нет
  домашнего каталога. В `compose.yaml` это закрыто опциями `spark.jars.ivy=/tmp/.ivy2` и `-Duser.home=/tmp`,
  проверьте, что их не убрали.
- **`java.io.FileNotFoundException: derby.log (Read-only file system)` и `ERROR XBM01: Startup failed`.** `spark-sql` создаёт
  Derby-метастор Hive в каталоге запуска. Папка проекта смонтирована только на чтение, поэтому
  `working_dir` контейнера стоит в `/tmp`.
- **Spark не видит таблицы из шагов 2 и 3.** Python-скрипты и `compose.yaml` должны смотреть в одно
  хранилище: либо оба без `PAIMON_WAREHOUSE` (папка `warehouse` рядом со скриптами), либо оба с одним
  абсолютным путём в этой переменной.
