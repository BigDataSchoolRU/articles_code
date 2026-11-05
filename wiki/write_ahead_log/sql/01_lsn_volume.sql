-- postgres 18.6, прогнано на стенде 2026-11-05: LSN, сегменты и объём журнала от вставки 100 тыс. строк
\pset footer off
SHOW wal_level;
SHOW wal_segment_size;

DROP TABLE IF EXISTS orders_logged, orders_unlogged;
CREATE TABLE orders_logged (id int PRIMARY KEY, amount numeric, note text);
CREATE UNLOGGED TABLE orders_unlogged (id int PRIMARY KEY, amount numeric, note text);

-- обнуляем счётчики журнала и запоминаем позицию в нём до вставки
SELECT pg_stat_reset_shared('wal') \g /dev/null
SELECT pg_current_wal_lsn() AS lsn_before,
       pg_walfile_name(pg_current_wal_lsn()) AS segment_before \gset
\echo lsn_before = :lsn_before, сегмент :segment_before

INSERT INTO orders_logged
SELECT g, round((random() * 1000)::numeric, 2), 'order ' || g
FROM generate_series(1, 100000) g;

SELECT pg_current_wal_lsn() AS lsn_after,
       pg_walfile_name(pg_current_wal_lsn()) AS segment_after \gset
\echo lsn_after  = :lsn_after, сегмент :segment_after

-- сколько байт журнала дала вставка: разность двух LSN
SELECT pg_size_pretty(pg_wal_lsn_diff(:'lsn_after', :'lsn_before')) AS wal_written,
       pg_size_pretty(pg_total_relation_size('orders_logged')) AS table_with_index;

-- та же вставка в UNLOGGED-таблицу: данные в журнал не пишутся
SELECT pg_current_wal_lsn() AS lsn_u0 \gset
INSERT INTO orders_unlogged
SELECT g, round((random() * 1000)::numeric, 2), 'order ' || g
FROM generate_series(1, 100000) g;
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), :'lsn_u0')) AS wal_written_unlogged;

-- накопительная статистика журнала; счётчики backend сбрасываются в общую память не сразу
SELECT pg_stat_force_next_flush() \g /dev/null
SELECT wal_records, wal_fpi, pg_size_pretty(wal_bytes) AS wal_bytes, wal_buffers_full
FROM pg_stat_wal;
