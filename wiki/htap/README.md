# HTAP (Hybrid Transactional/Analytical Processing)

Код к статье [HTAP](https://bigdataschool.ru/wiki/htap/) в Wiki BigDataSchool.

Демо показывает, зачем вообще понадобился HTAP: сначала транзакционная и аналитическая
нагрузка сталкиваются в одном строковом хранилище, потом аналитика уезжает в колоночную
копию тех же данных. Это ручная сборка того, что HTAP-системы вроде TiDB с TiFlash или
AlloyDB делают внутри себя.

## Состав

| Файл | Что делает |
|---|---|
| `oltp_under_analytics.py` | Таблица заказов на 12 млн строк в PostgreSQL. Меряет латентность точечных UPDATE в тишине и под шестью параллельными агрегациями по всей таблице. |
| `columnar_replica.py` | Реплицирует ту же таблицу в колоночное хранилище DuckDB, гоняет там тот же SQL и меряет размер, время запроса и окно лага репликации. |
| `RUNBOOK.md` | Пошаговый прогон обоих демо с нуля: окружение, команды, что должно быть в выводе, типовые грабли. |

## Окружение

PostgreSQL 18, Python 3.12, DuckDB 1.5.5, psycopg 3.3.4, pytz. Понадобится около 2 ГБ
на диске под таблицу, снимок и колоночный файл. Полный прогон занимает около четырёх минут.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install "psycopg[binary]" duckdb pytz
createdb htap_demo
./.venv/bin/python3 oltp_under_analytics.py
./.venv/bin/python3 columnar_replica.py
```

Строка подключения задаётся переменной `HTAP_DSN`, по умолчанию это `dbname=htap_demo`
через локальный сокет. Подробности и разбор типовых ошибок в `RUNBOOK.md`.
