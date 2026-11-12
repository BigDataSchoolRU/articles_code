# OpenLineage на Python и Apache Spark

Код к Wiki-статье «OpenLineage»: https://bigdataschool.ru/wiki/openlineage/

Два производителя событий OpenLineage и один самодельный потребитель. Python-конвейер сам
сообщает о своих запусках через клиент `openlineage-python`, Spark-задание не знает про
OpenLineage ничего, события за него шлёт listener `openlineage-spark`. Сборщик на стандартной
библиотеке Python принимает события по HTTP и собирает из них граф по паре `namespace` и `name`
датасета.

## Файлы

| Файл | Что делает |
|---|---|
| `collector.py` | сборщик событий на `http.server`: `serve` принимает POST `/api/v1/lineage`, `graph` строит граф и колоночный lineage, `show` печатает одно событие целиком |
| `emit_pipeline.py` | конвейер из двух заданий (CSV → `staging.orders_clean` → `mart.daily_revenue` в SQLite), события START, FAIL и COMPLETE с фасетами схемы, SQL, ошибки и колоночного lineage; режим `broken` называет тот же CSV относительным путём |
| `openlineage.yml` | конфигурация клиента: составной транспорт, HTTP в сборщик плюс запись в файл `emitted.jsonl` |
| `spark_job.py` | обычное Spark-задание: выручка по клиентам из CSV в Parquet, без единой строки OpenLineage |
| `docker-compose.yml` | Spark 4.0.4 в образе `apache/spark` и `spark-submit` с listener'ом OpenLineage |
| `log4j2.properties` | оставляет в консоли Spark только ошибки и строки об отправке событий |
| `data/orders.csv` | 10 заказов, общий источник для обоих производителей |
| `requirements.txt` | `openlineage-python==1.55.0` |
| `RUNBOOK.md` | пошаговый запуск с ожидаемым выводом |

## Окружение

Python 3.12, Docker с Compose v2, Linux (сеть хоста для контейнера Spark), около 3 ГБ свободной
памяти и 2.2 ГБ диска под образ Spark. Проверено с `openlineage-python` 1.55.0,
`openlineage-spark_2.13` 1.55.0, Apache Spark 4.0.4, спецификацией OpenLineage 2-0-2.

## Как запустить

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p jars && curl -sSfL -o jars/openlineage-spark_2.13-1.55.0.jar \
  https://repo1.maven.org/maven2/io/openlineage/openlineage-spark_2.13/1.55.0/openlineage-spark_2.13-1.55.0.jar
.venv/bin/python collector.py serve &          # сборщик на 127.0.0.1:5000
.venv/bin/python emit_pipeline.py              # Python-производитель
docker compose run --rm spark                  # Spark-производитель
.venv/bin/python emit_pipeline.py broken       # тот же файл под другим именем
.venv/bin/python collector.py graph            # граф из всех событий
```

Подробности и ожидаемый вывод каждого шага в `RUNBOOK.md`.
