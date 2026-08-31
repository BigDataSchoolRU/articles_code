# OLAP (Online Analytical Processing)

Статья: https://bigdataschool.ru/wiki/olap/

Демо строит классическую звёздную схему в PostgreSQL, показывает операции над кубом
(slice, dice, roll-up, CUBE, pivot) обычным SQL, а затем сравнивает ту же агрегацию на
строковом (ROLAP) и колоночном (DuckDB) движках.

## Состав

| Файл | Что делает |
|---|---|
| `db_setup.py` | Пересоздаёт базу `olap_demo`: три измерения (дата, товар, магазин) и факт продаж на 1 млн строк |
| `cube_operations.py` | Slice, dice, roll-up (`GROUP BY ROLLUP`), CUBE (`GROUP BY CUBE`), pivot (`FILTER`) на звёздной схеме |
| `columnar_compare.py` | Сравнивает время одной и той же агрегации в PostgreSQL (join) и DuckDB (колоночная физическая таблица) |
| `RUNBOOK.md` | Пошаговый прогон демо на своей машине |

## Окружение

PostgreSQL 14+, Python 3.10+ с пакетами `psycopg[binary]`, `duckdb`, `pandas`.

## Как запустить

```bash
pip install "psycopg[binary]" duckdb pandas
python3 db_setup.py
python3 cube_operations.py
python3 columnar_compare.py
```

Подробности и ожидаемый вывод каждого шага — в [RUNBOOK.md](RUNBOOK.md).
