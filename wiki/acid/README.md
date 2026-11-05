# ACID

Код к статье [ACID](https://bigdataschool.ru/wiki/acid/).

Четыре гарантии транзакции на одном контейнере PostgreSQL 18.6. Atomicity: перевод между
счетами откатывается целиком, `SAVEPOINT` откатывает часть. Consistency: `CHECK` и внешние
ключи, в том числе отложенная проверка на `COMMIT`. Isolation: грязное, неповторяемое и
фантомное чтение, потерянное обновление и write skew на двух сессиях с явным чередованием
шагов, ошибка 40001 и повтор транзакции. Durability: подтверждённые строки переживают
`docker kill -s KILL`, незафиксированная нет.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker, порт `127.0.0.1:55435` |
| `requirements.txt` | `psycopg[binary]==3.3.8` для демо изоляции |
| `acid_demo.sh` | запускает сценарии по очереди или по одному: `all`, `atomicity`, `consistency`, `isolation`, `write_skew`, `durability` |
| `sql/01_atomicity.sql` | перевод с ошибкой посередине, `COMMIT` превращается в `ROLLBACK`, статус отменённой транзакции, версии строк на странице через `pageinspect`, `SAVEPOINT` |
| `sql/02_consistency.sql` | `CHECK (balance >= 0)`, внешний ключ, `SET CONSTRAINTS ALL DEFERRED` и ошибка на `COMMIT` |
| `isolation_demo.py` | две сессии psycopg: `reads` (Read Uncommitted, Read Committed, Repeatable Read), `lost_update`, `write_skew` (Repeatable Read против Serializable, `SIReadLock`, повтор по 40001) |
| `sql/05_before_crash.sql` | пять подтверждённых транзакций перед сбоем |
| `sql/05_after_crash.sql` | что осталось после восстановления по журналу |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `postgres:18.6`, Python 3.10 или новее.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
./acid_demo.sh all
docker compose down -v
```
