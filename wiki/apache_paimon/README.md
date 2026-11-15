# Apache Paimon

Код к статье [Apache Paimon](https://bigdataschool.ru/wiki/apache_paimon/).

Три демо на Apache Paimon 2.1.0. Таблицы пишет Python-клиент `pypaimon` 2.1.0 в каталог `filesystem`
в локальной папке, без JVM и без кластера. Компакцию делает Spark 4.0.4 с `paimon-spark-4.0_2.13` 2.1.0
поверх тех же файлов.

Первое демо создаёт таблицу заказов с первичным ключом на два бакета. Два коммита upsert'ов, чтение
отдаёт последнюю версию строки по ключу (merge-on-read). Потоковый читатель получает изменения второго
снапшота из файлов changelog. Скрипт печатает снапшоты, файлы данных по бакетам и уровням LSM-дерева и
содержимое каталога таблицы.

Второе демо отправляет одну и ту же последовательность из трёх коммитов по одному ключу в четыре
таблицы с разным merge engine: `deduplicate`, `partial-update`, `aggregation` и `first-row`.

Третье демо в Spark SQL запускает `CALL sys.compact` и через системные таблицы `$files` и `$snapshots`
показывает, как файлы уровня 0 сливаются в один файл верхнего уровня и появляется снапшот `COMPACT`.

## Состав

| Файл | Что делает |
|---|---|
| `requirements.txt` | `pypaimon==2.1.0`, `pyarrow==19.0.1`, `pandas==2.3.3` |
| `pk_table_demo.py` | таблица `shop.orders` с первичным ключом: два коммита, чтение, changelog, снапшоты, файлы по уровням LSM, каталог таблицы |
| `merge_engine_demo.py` | таблицы `engines.orders_*`: три коммита по одному ключу и результат четырёх merge engine |
| `compaction.sql` | Spark SQL: файлы до и после `CALL sys.compact`, снапшоты, чтение `first-row` до и после компакции |
| `compose.yaml` | `spark-sql` в образе `apache/spark:4.0.4-scala2.13-java17-python3-ubuntu` с jar Paimon и каталогом на папке `warehouse` |
| `log4j2.properties` | Spark пишет в консоль только ошибки |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Python 3.9 или новее, venv с `pypaimon` занимает около 560 МБ (pyarrow, pandas, polars). Для третьего
демо нужен Docker с Compose 2.23 или новее (встроенные `configs`) и jar `paimon-spark-4.0_2.13-2.1.0.jar`
(47 МБ, Maven Central). Таблицы демо занимают меньше 1 МБ.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pk_table_demo.py
.venv/bin/python merge_engine_demo.py
mkdir -p jars && curl -sSfo jars/paimon-spark-4.0_2.13-2.1.0.jar \
  https://repo1.maven.org/maven2/org/apache/paimon/paimon-spark-4.0_2.13/2.1.0/paimon-spark-4.0_2.13-2.1.0.jar
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose run --rm spark-sql
```
