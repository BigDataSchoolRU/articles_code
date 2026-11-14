# Apache Fluss

Код к статье [Apache Fluss](https://bigdataschool.ru/wiki/apache_fluss/).

Два демо на локальном кластере Apache Fluss 1.0.0 (ZooKeeper, CoordinatorServer и TabletServer из
бинарного дистрибутива) и Python-клиенте `pyfluss` 1.0.0, без Flink.

Первое демо работает с таблицей с первичным ключом (Primary Key Table). Upsert, частичное обновление
и удаление меняют строку в KV-хранилище. Lookup по ключу сразу видит изменения. Та же таблица отдаёт
потоковому читателю changelog с событиями `+I`, `-U`, `+U`, `-D` и офсетами. Отдельно замеряется
задержка lookup: клиент копит запросы в батч и ждёт его заполнения до 100 мс.

Второе демо работает с лог-таблицей (Log Table) в формате Arrow на 12 колонок. Полное чтение
сравнивается с проекцией двух колонок: сервер вырезает их сам, и по сети идёт около 4% байтов.
Затем фильтр по дню проверяется на таблице без колоночной статистики и на таблице, где она включена.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | контейнер с JDK 17, внутри которого `bin/local-cluster.sh` поднимает три JVM; сеть хоста, порт клиента 9123 |
| `server.yaml` | конфигурация кластера: `conf/server.yaml` из дистрибутива плюс лимиты памяти JVM |
| `requirements.txt` | `pyfluss==1.0.0` (тянет pyarrow и pandas) |
| `pk_table_demo.py` | таблица `shop.orders` с первичным ключом: upsert, partial update, delete, lookup, задержка lookup, чтение changelog |
| `log_table_projection.py` | лог-таблицы `shop.clicks` и `shop.clicks_stats`: запись Arrow, полное чтение, проекция, фильтр со статистикой и без неё, байты по сети |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Дистрибутив `fluss-1.0.0-bin.tgz` (522 МБ, для демо нужны только `lib/`, `bin/` и `conf/`, около 86 МБ).
Для кластера нужен JDK 17 или новее либо Docker на Linux. Для клиента нужен Python 3.9 или новее,
venv с `pyfluss` занимает около 370 МБ. Кластер в работе занимает около 400 МиБ памяти. Свободного
места на диске должно быть больше 15%: при заполнении диска на 85% TabletServer перестаёт принимать
запись.

## Как запустить

```bash
curl -sL https://dlcdn.apache.org/fluss/fluss-1.0.0/fluss-1.0.0-bin.tgz \
  | tar xzf - fluss-1.0.0/lib fluss-1.0.0/bin fluss-1.0.0/conf
docker compose up -d --wait            # или с локальным JDK 17: см. RUNBOOK, шаг 2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pk_table_demo.py
.venv/bin/python log_table_projection.py
docker compose down
```
