# MVCC

Код к статье [MVCC](https://bigdataschool.ru/wiki/mvcc/).

Многоверсионность PostgreSQL 18.6 на одном контейнере. Видно, что UPDATE и DELETE оставляют
на странице старую версию строки с заполненным `xmax`. Чтение и запись на двух сессиях не ждут
друг друга, а снимок в Repeatable Read держится до конца транзакции. HOT-обновление обходится
без записи в индекс и зависит от `fillfactor`. Открытая транзакция не даёт VACUUM удалить
мёртвые версии. Заморозка помечает `xmin` версий как замороженный и сбрасывает возраст таблицы.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker, порт `127.0.0.1:55436` |
| `requirements.txt` | `psycopg[binary]==3.3.8` для демо на двух сессиях |
| `mvcc_demo.sh` | запускает сценарии по очереди или по одному: `all`, `versions`, `snapshot`, `hot`, `horizon`, `freeze` |
| `sql/01_versions.sql` | `xmin`, `xmax`, `ctid` после INSERT, UPDATE и DELETE, страница таблицы через `pageinspect`, DELETE с откатом |
| `snapshot_demo.py` | две сессии psycopg: `snapshot` (Repeatable Read против Read Committed, `pg_current_snapshot()`), `horizon` (открытая транзакция, `VACUUM (VERBOSE)`, `VACUUM FULL`) |
| `sql/03_hot.sql` | цепочка HOT на странице, записи в индексе, перенаправление после VACUUM, `fillfactor` 100 против 90, `n_tup_hot_upd` |
| `sql/05_freeze.sql` | пороги заморозки, `age(relfrozenxid)`, `VACUUM (FREEZE)`, флаг `HEAP_XMIN_FROZEN`, карта видимости |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `postgres:18.6`, Python 3.10 или новее.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
./mvcc_demo.sh all
docker compose down -v
```
