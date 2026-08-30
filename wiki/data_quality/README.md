# data_quality

Код к статье [Качество данных (Data Quality)](https://bigdataschool.ru/wiki/data_quality/) на
Wiki BigDataSchool.

## Файлы

- `db_setup.py` — создаёт демо-базу `data_quality_demo` с таблицей `orders` (5000 строк),
  часть которых испорчена намеренно: дубли `order_id`, `NULL` в обязательных полях,
  отрицательные суммы, некорректный формат email, разнобой регистра в `status`, даты заказа
  в будущем.
- `expectations_demo.py` — строит Expectation Suite из 7 проверок в Great Expectations (GX Core),
  по одной-две на дименсию качества данных, запускает Checkpoint и печатает результат вместе
  со ссылкой на отчёт Data Docs.
- `RUNBOOK.md` — пошаговый прогон демо с нуля, включая типовые ошибки.

## Окружение

Python 3.11+, PostgreSQL 14+ с правом создавать базы. Пакеты из `requirements.txt`:
`great_expectations` 1.11.1, `psycopg` 3.3.4, `psycopg2-binary` 2.9.12.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python3 db_setup.py
./.venv/bin/python3 expectations_demo.py
```

Подробности и разбор возможных ошибок — в `RUNBOOK.md`.
