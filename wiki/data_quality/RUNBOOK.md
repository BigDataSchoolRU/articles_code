# RUNBOOK: проверка качества данных с Great Expectations (GX Core)

Демо к статье [Качество данных (Data Quality)](https://bigdataschool.ru/wiki/data_quality/) на
bigdataschool.ru: создаёт таблицу с намеренными дефектами и проверяет её набором Expectation,
покрывающим основные дименсии качества данных.

## Окружение

- Python 3.11+
- PostgreSQL 14+, доступный локально с правом создавать базы
- Пакеты из `requirements.txt`: `great_expectations` 1.11.1, `psycopg` 3.3.4,
  `psycopg2-binary` 2.9.12

Подставьте свои значения:

- `PGUSER` — пользователь PostgreSQL с правом `CREATEDB` (в примерах ниже `techfriends`, замените
  на своего)
- Адрес PostgreSQL — в примерах `localhost:5432`, если ваш сервер слушает на другом хосте или
  порту, поправьте строку подключения в `db_setup.py` и `expectations_demo.py`

## Шаг 1. Окружение и зависимости

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Проверка: `./.venv/bin/pip show great_expectations` печатает `Version: 1.11.1` без ошибок.

## Шаг 2. Демо-база с дефектами

```bash
./.venv/bin/python3 db_setup.py
```

Скрипт создаёт базу `data_quality_demo`, если её ещё нет, и каждый раз заново создаёт таблицу
`orders` (`drop table if exists` перед `create table`), наполняя её 5000 строками, часть которых
испорчена намеренно: дубли `order_id`, `NULL` в `customer_email`/`amount`, отрицательные суммы,
некорректный формат email, разнобой регистра в `status` (`paid`/`PAID`/`Paid`), даты заказа в
будущем. Скрипт идемпотентен: базу можно удалить целиком, повторный запуск пересоздаст всё с нуля.

Ожидаемый вывод:

```
orders: 5000 строк загружено в базу data_quality_demo
```

Как понять, что шаг прошёл: строка с числом `5000` без traceback. Если PostgreSQL недоступен по
адресу из строки подключения, скрипт упадёт в `ensure_database()` с `psycopg.OperationalError` —
см. первый пункт раздела «если не так».

## Шаг 3. Проверка качества данных

```bash
./.venv/bin/python3 expectations_demo.py
```

Скрипт строит Data Context, Expectation Suite из 7 проверок (по одной-две на дименсию),
запускает Checkpoint и печатает результат по каждому Expectation плюс ссылку на отчёт Data Docs.

Ожидаемый вывод (числа `unexpected` могут отличаться на единицы из-за случайного зерна, если вы
меняли `db_setup.py`):

```
Checkpoint выполнен за 0.3-0.5 с, общий success=False

[FAIL] expect_column_values_to_not_be_null column=customer_email   unexpected=26
[FAIL] expect_column_values_to_match_regex column=customer_email   unexpected=15
[FAIL] expect_column_values_to_not_be_null column=amount           unexpected=26
[FAIL] expect_column_values_to_be_between column=amount           unexpected=20
[FAIL] expect_column_values_to_be_unique column=order_id         unexpected=60
[FAIL] expect_column_values_to_be_in_set column=status           unexpected=40
[FAIL] expect_column_values_to_be_between column=order_date       unexpected=12

Data Docs: file:///.../gx/uncommitted/data_docs/local_site/index.html
```

Как понять, что шаг прошёл: `success=False` — это ожидаемый результат демо, таблица специально
испорчена. Семь строк `[FAIL]` с ненулевым `unexpected` подтверждают, что каждая проверка
действительно нашла свои дефекты, а не молча пропустила данные. Откройте ссылку `Data Docs` в
браузере — там тот же результат в виде HTML-отчёта с разбивкой по Expectation.

## Если не так

- **`psycopg.OperationalError: connection failed`** — PostgreSQL не запущен или строка
  подключения в `db_setup.py`/`expectations_demo.py` указывает не туда. Проверьте, что сервер
  слушает адрес из строки подключения, и что `PGUSER` существует и имеет право `CREATEDB`.
- **`TestConnectionError` при создании `data_source`** — тот же адрес подключения, но уже со
  стороны GX Core: он ходит в базу отдельным подключением при добавлении Data Source/Asset.
  Проверьте `CONNECTION_STRING` в `expectations_demo.py`.
- **Все `unexpected` равны нулю** — таблица `orders` не пересоздана дефектной версией из
  `db_setup.py` (например, вы указали на чужую базу с тем же именем). Пересоздайте базу шагом 2.
- **Первый запуск создаёт папку `gx/`** рядом со скриптами — это рабочие файлы GX Core
  (конфигурация Data Context, отчёт Data Docs), они пересоздаются с нуля при каждом запуске
  `expectations_demo.py`.
