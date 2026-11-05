-- postgres 18.6, прогнано на стенде 2026-11-05: полностраничный образ после контрольной точки
\pset footer off
SHOW full_page_writes;
-- с PostgreSQL 18 initdb включает контрольные суммы по умолчанию, и hint-биты тоже попадают в журнал
SHOW data_checksums;

DROP TABLE IF EXISTS accounts;
-- fillfactor 50 оставляет место на странице, и UPDATE остаётся на ней же (HOT)
CREATE TABLE accounts (id int PRIMARY KEY, balance numeric) WITH (fillfactor = 50);
INSERT INTO accounts SELECT g, 1000 FROM generate_series(1, 1000) g;
-- VACUUM проставляет hint-биты заранее, чтобы в замер попал только сам UPDATE
VACUUM accounts;

-- первое изменение страницы после CHECKPOINT пишет в журнал её полный образ (8 КБ)
CHECKPOINT;
SELECT pg_current_wal_lsn() AS fpw_start \gset
EXPLAIN (ANALYZE, WAL, COSTS OFF, TIMING OFF, SUMMARY OFF)
UPDATE accounts SET balance = balance + 1 WHERE id = 1;

-- повторное изменение той же страницы до следующей контрольной точки: только сама запись
EXPLAIN (ANALYZE, WAL, COSTS OFF, TIMING OFF, SUMMARY OFF)
UPDATE accounts SET balance = balance + 1 WHERE id = 1;
SELECT pg_current_wal_lsn() AS fpw_end \gset

-- те же два UPDATE глазами pg_waldump: у первой записи блок помечен FPW
\setenv FPW_START :fpw_start
\setenv FPW_END :fpw_end
\! pg_waldump -p "$PGDATA/pg_wal" -s "$FPW_START" -e "$FPW_END" -r Heap

-- то же самое со сжатием образов lz4: VACUUM возвращает страницу в исходное состояние,
-- и первый UPDATE после CHECKPOINT снова пишет два образа, но сжатых
SET wal_compression = lz4;
VACUUM accounts;
CHECKPOINT;
EXPLAIN (ANALYZE, WAL, COSTS OFF, TIMING OFF, SUMMARY OFF)
UPDATE accounts SET balance = balance + 1 WHERE id = 1;
RESET wal_compression;
