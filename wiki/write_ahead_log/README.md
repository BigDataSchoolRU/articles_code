# WAL (Write-Ahead Log)

Код к статье [WAL](https://bigdataschool.ru/wiki/write_ahead_log/).

Журнал предзаписи PostgreSQL изнутри на одном контейнере: позиция в журнале (LSN) и его
объём, полностраничные образы после контрольной точки, цена надёжного коммита, слот
репликации, который не даёт удалять сегменты, и восстановление после аварийной остановки.
Python не нужен, всё идёт через `psql`, `pgbench` и `pg_waldump` из образа PostgreSQL.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker, `max_wal_size=64MB`, `checkpoint_timeout=30min`, порт 55434 |
| `wal_demo.sh` | запускает сценарии по очереди или по одному: `all`, `lsn`, `fpw`, `commit`, `slot`, `crash` |
| `sql/01_lsn_volume.sql` | LSN до и после вставки 100 тыс. строк, имя сегмента, объём журнала, UNLOGGED-таблица, `pg_stat_wal` |
| `sql/02_full_page_writes.sql` | первый и повторный UPDATE строки после `CHECKPOINT` в `EXPLAIN (ANALYZE, WAL)`, разбор записей `pg_waldump`, сжатие образов lz4 |
| `insert.sql` | скрипт pgbench: одна вставка на транзакцию |
| `sql/03_commit_io.sql` | запись и fsync журнала по типам процессов из `pg_stat_io` |
| `sql/04_slot_retention.sql` | брошенный физический слот держит сегменты `pg_wal`, `wal_status`, потолок `max_slot_wal_keep_size` |
| `sql/05_before_crash.sql` | контрольная точка, пять подтверждённых транзакций, точка REDO перед сбоем |
| `sql/05_after_crash.sql` | что осталось после проигрывания журнала |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `postgres:18.6`. Свободно около 1 ГБ диска под том.

## Как запустить

```bash
docker compose up -d --wait
./wal_demo.sh all
docker compose down -v
```
