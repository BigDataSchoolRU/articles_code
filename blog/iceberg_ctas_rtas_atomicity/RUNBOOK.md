# RUNBOOK: атомарные CTAS и RTAS в Apache Iceberg на Spark

Демо к статье «Атомарные CTAS и RTAS в Apache Iceberg на Spark». Всё работает локально, без Docker и без внешних сервисов.

## Окружение

- Linux или macOS, 4 ГБ свободной памяти, около 1,5 ГБ на диске.
- Python 3.11 или 3.12.
- Java 17 (подходит и 11). Нужна для JVM Spark. Если Java не установлена, `selfcheck.py` сам скачает Eclipse Temurin 17 в каталог `.jdk` через пакет `install-jdk`.
- Доступ к Maven Central при первом запуске: Spark скачает `org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:1.10.1` в локальный кеш Ivy. Для автоскачивания JDK нужен доступ к api.adoptium.net.

Пины версий:

| Компонент | Версия |
|---|---|
| pyspark | 3.5.6 |
| py4j | 0.10.9.7 |
| install-jdk | 1.1.0 |
| iceberg-spark-runtime-3.5_2.12 | 1.10.1 |

Почему 1.10.1, а не 1.12.0: страница релизов называет 1.12.0 последней, но дату релиза не показывает. 1.10.1 вышел 22 декабря 2025 года и собран под Spark 3.5. Чтобы проверить 1.12.0, поменяйте константу `ICEBERG_VERSION` в демо, если в Maven Central есть артефакт `iceberg-spark-runtime-3.5_2.12` этой версии.

Переменные окружения:

- `JAVA_HOME` — если `java` нет в `PATH`. При запуске через `selfcheck.py` можно не выставлять: он найдёт JDK в `.jdk` или скачает его.

Ключей, токенов и паролей демо не требуют.

Каталоги в одной сессии Spark:

- `lake` — `org.apache.iceberg.spark.SparkCatalog`, `type=hadoop`, warehouse в `data/<демо>/lake`. Каталог hadoop учебный: в проде берите REST catalog, Hive Metastore, Nessie или Glue.
- `spark_catalog` — `org.apache.iceberg.spark.SparkSessionCatalog` поверх встроенного in-memory session catalog, Iceberg-часть в `data/<демо>/session`, не-Iceberg таблицы в `data/<демо>/spark`.

Каждое демо перед стартом удаляет и создаёт заново свой каталог `data/<имя демо>/`.

Свойство владельца в демо называется `team`, а не `owner`: в Spark 3.5 `owner` зарезервирован, и `TBLPROPERTIES ('owner' = ...)` падает с `UNSUPPORTED_FEATURE.SET_TABLE_PROPERTY`.

## Шаг 1. Виртуальное окружение, пакеты и Java

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
java -version
```

Что в выводе: pip заканчивает строкой `Successfully installed ...` с `pyspark-3.5.6`, `py4j-0.10.9.7` и `install-jdk-1.1.0`. `java -version` печатает версию 17 или 11.

Если `java` не найдена, поставьте JDK локально в каталог статьи и выставьте `JAVA_HOME` на распакованный каталог:

```bash
.venv/bin/python -c "import jdk; print(jdk.install('17', path='.jdk'))"
```

Шаг прошёл, если `.venv/bin/python -c "import pyspark; print(pyspark.__version__)"` печатает `3.5.6`, а `java -version` (или `$JAVA_HOME/bin/java -version`) печатает версию.

## Шаг 2. Базовый CTAS

```bash
.venv/bin/python 01_ctas_basic.py
```

Что в выводе:

- `SHOW TABLES IN lake.db` с таблицей `orders_src`;
- метатаблица snapshots с одной строкой, `operation = append`, `total_records = 10000`;
- список файлов метаданных: один `v1.metadata.json` и `version-hint.text`;
- в шаге 4 у `lake.db.orders_copy` партиционирование и свойства источника (`team`, `history.expire.max-snapshot-age-ms`) не повторены, у `lake.db.orders_copy_explicit` они есть.

Шаг прошёл, если скрипт завершился с кодом 0 и в последней строке есть «Вывод: CTAS без PARTITIONED BY ...».

## Шаг 3. CTAS с падением посередине

```bash
.venv/bin/python 02_ctas_failure.py
```

UDF `boom_at` бросает `RuntimeError: INJECTED_FAILURE at order_id=7000`. Для каждого случая скрипт печатает три канала проверки: `SHOW TABLES`, `SELECT count(*)` и файлы на диске.

Что в выводе:

- шаг 1 — эталон: как успешная Iceberg-таблица выглядит в `spark_catalog`. Обратите внимание, видит ли её `SHOW TABLES`: листинг SparkSessionCatalog идёт через встроенный session catalog;
- шаг 2 (`lake`, SparkCatalog): строка `запрос упал: ... INJECTED_FAILURE` и итог «после сбоя таблицы нет ни в листинге, ни для SELECT»;
- шаги 3 и 4 (`spark_catalog`, Iceberg и parquet): итог печатается по факту. Запишите, какой из двух итогов вы получили: это и есть поведение SparkSessionCatalog на вашем стенде;
- шаг 5: повторный CTAS с тем же именем в `lake`.

Шаг прошёл, если у всех трёх случаев есть строка `запрос упал` с маркером `INJECTED_FAILURE` и строка `итог:`.

## Шаг 4. RTAS со сменой схемы и партиционирования

```bash
.venv/bin/python 03_rtas_schema_change.py
```

Что в выводе:

- шаг 1: схема с `customer_id` и `region`, партиционирование `region`, свойство `team = sales`;
- шаг 2: схема без `customer_id`, `amount` типа `decimal(12,2)`, колонка `region_code`, партиционирование `days(order_ts)`, свойство `quality = checked`. Строка про `team` показывает, слились ли свойства;
- history и snapshots: два snapshot. Посмотрите на `parent_id` нового snapshot и `is_current_ancestor` старого;
- шаг 3: после `REPLACE TABLE ... AS SELECT` без `PARTITIONED BY` строка `spec: было days(order_ts), стало ...`;
- шаг 4: исходный snapshot читается через `VERSION AS OF` со старой схемой, в выводе `строк 10000`.

Шаг прошёл, если код 0 и в шаге 4 напечатано число строк исходного snapshot.

## Шаг 5. RTAS с падением и откат

```bash
.venv/bin/python 04_rtas_failure_rollback.py
```

Что в выводе:

- шаг 2: `RTAS упал: ... INJECTED_FAILURE`, затем сравнение «до/после». У текущего snapshot, числа строк, схемы и партиционирования должно стоять «не изменилось». Строка `лишних parquet-файлов после сбоя` показывает, остались ли сироты на диске;
- шаг 3: успешный RTAS, `строк: 3334` (только EU), history;
- шаг 4: либо `rollback_to_snapshot выполнен`, либо `rollback_to_snapshot отказал: ...` и попытка `set_current_snapshot`. Какая ветка сработала, зависит от того, считается ли snapshot до RTAS предком текущего (смотрите `is_current_ancestor` в history шага 3);
- шаг 5: сравнение с исходным состоянием, первые строки текущего состояния и попытка прочитать те же строки через `VERSION AS OF` (на стенде она может упасть с `Py4JJavaError`, и повтор без векторизации тоже), history после отката и три строки `итог, ...`.

Шаг прошёл, если код 0 и есть строка `итог, строк: как до RTAS`. Если схема и партиционирование после отката остались новыми (`итог, схема: НЕ как до RTAS`), это наблюдение, а не ошибка стенда.

## Шаг 6. Два шага и INSERT OVERWRITE с падением

```bash
.venv/bin/python 05_two_step_and_overwrite.py
```

Что в выводе:

- шаг 1: таблица есть в `SHOW TABLES`, `строк: 0`, `snapshots: 0`;
- шаг 2: после упавшего `INSERT INTO` итог «пустая таблица осталась в каталоге»;
- шаг 4: после упавшего `INSERT OVERWRITE` строки, snapshot, схема и партиционирование «не изменилось»;
- шаг 5: snapshot с `operation = overwrite`, spec «сохранён».

Шаг прошёл, если код 0 и в шаге 2 напечатан итог про пустую таблицу.

## Шаг 7. Замер RTAS против INSERT OVERWRITE

```bash
.venv/bin/python 06_compare_rtas_vs_overwrite.py
```

Что в выводе:

- таблица времени: по 3 прогона каждого варианта и медиана в миллисекундах;
- для `mart_rtas` и `mart_overwrite`: число snapshots, операции, сколько snapshot имеют `parent_id`, сколько `metadata.json` на диске;
- `строк, которые есть в mart_rtas и нет в mart_overwrite: 0`.

Шаг прошёл, если код 0 и разница строк равна 0. Цифры времени зависят от машины, сравнивайте варианты между собой, а не с чужим стендом.

## Шаг 8. Полный прогон одной командой

```bash
.venv/bin/python selfcheck.py
cat run_output.txt
cat .status
```

Что в выводе: в `run_output.txt` первая строка с датой и `python3 3.x.y`, затем строка, откуда взята Java (`JAVA_HOME`, `PATH`, кеш `.jdk` или скачан Temurin 17), строка `java: ... version "17..."`, блоки `########## DEMO <файл> ##########` и `[OK]` или `[FAIL]` после каждого, в конце `########## ИТОГ ##########`. В `.status` одна строка вида `0 2026-11-21T10:00:00Z`.

Шаг прошёл, если `.status` начинается с `0`. Фоновый вариант: `.venv/bin/python selfcheck.py --detach` сразу возвращает управление, `.status` появится по окончании.

## Если не так

- `JAVA_HOME is not set` и `JAVA_GATEWAY_EXITED`: Java не найдена. Поставьте JDK 17 и выставьте `JAVA_HOME`, либо скачайте его командой из шага 1, либо запускайте через `selfcheck.py`, который скачает Temurin сам.
- В `run_output.txt` строка `java: не нашли и не смогли скачать Temurin 17`: нет доступа к api.adoptium.net. Поставьте JDK вручную и выставьте `JAVA_HOME`.
- Зависание или ошибка на `:: resolving dependencies`: нет доступа к Maven Central. Проверьте сеть или прокси, повторите запуск, артефакт закешируется.
- `ParseException: [UNSUPPORTED_FEATURE.SET_TABLE_PROPERTY] ... owner is a reserved table property`: в `TBLPROPERTIES` попало `owner`. В Spark 3.5 это зарезервированное свойство, его задаёт сам Spark. Используйте другое имя ключа, в демо это `team`.
- `ClassNotFoundException` для `org.apache.iceberg.spark.SparkCatalog`: версия pyspark не 3.5.x или изменена константа `ICEBERG_VERSION` на версию без артефакта `iceberg-spark-runtime-3.5_2.12`.
- `Python worker exited unexpectedly` вместо `INJECTED_FAILURE`: воркер запускается другим интерпретатором. Запускайте демо через `.venv/bin/python`, демо само выставляет `PYSPARK_PYTHON`.
- `OutOfMemoryError`: закройте лишние JVM или уменьшите `ROWS` в `06_compare_rtas_vs_overwrite.py`.
- `.status` начинается не с `0`: найдите в `run_output.txt` блок с `[FAIL]` и последние строки stderr под ним.
- Результаты шагов 3 и 5 отличаются от описанных: это не обязательно ошибка. Поведение SparkSessionCatalog и отката после RTAS зависит от версии Iceberg и реализации каталога, фиксируйте фактический вывод.
