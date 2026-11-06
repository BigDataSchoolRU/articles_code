-- postgres 18.6 в Docker, pageinspect и pg_visibility из contrib, прогнано на стенде 2026-11-06
-- Возраст XID и заморозка: что делает VACUUM (FREEZE) со старыми версиями.
CREATE EXTENSION IF NOT EXISTS pageinspect;
CREATE EXTENSION IF NOT EXISTS pg_visibility;
DROP TABLE IF EXISTS freeze_demo CASCADE;

\echo '--- 5.1 пороги заморозки и автовакуума на этом сервере (значения по умолчанию)'
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('autovacuum_freeze_max_age', 'vacuum_freeze_min_age', 'vacuum_freeze_table_age',
               'vacuum_failsafe_age', 'autovacuum_vacuum_threshold',
               'autovacuum_vacuum_scale_factor', 'autovacuum_vacuum_max_threshold',
               'autovacuum_vacuum_insert_threshold', 'vacuum_max_eager_freeze_failure_rate')
ORDER BY name;

\echo '--- 5.2 таблица и тысяча транзакций после неё, каждая со своим XID'
CREATE TABLE freeze_demo (id int PRIMARY KEY, v text) WITH (autovacuum_enabled = off);
INSERT INTO freeze_demo SELECT g, 'row ' || g FROM generate_series(1, 1000) g;
DO $$
BEGIN
    FOR i IN 1..1000 LOOP
        PERFORM pg_current_xact_id();
        COMMIT;
    END LOOP;
END $$;
SELECT pg_current_xact_id() AS current_xid,
       c.relfrozenxid, age(c.relfrozenxid) AS table_xid_age,
       (SELECT age(datfrozenxid) FROM pg_database WHERE datname = current_database()) AS db_xid_age
FROM pg_class c WHERE c.relname = 'freeze_demo';
SELECT min(xmin::text::bigint) AS rows_xmin, max(age(xmin)) AS rows_xmin_age FROM freeze_demo;

\set page_items 'SELECT lp, t_xmin, f.combined_flags, f.raw_flags FROM heap_page_items(get_raw_page(''freeze_demo'', 0)) h, LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) f ORDER BY lp LIMIT 2'
:page_items;
SELECT * FROM pg_visibility_map_summary('freeze_demo');
-- транзакции выше получили XID, но в WAL ничего не писали: их коммит сбрасывается на диск
-- фоном, в пределах wal_writer_delay (200 мс). VACUUM сразу после них замораживает версии,
-- но страницы all-visible не помечает (замечено на прогоне), поэтому ждём секунду
SELECT pg_sleep(1);

\echo '--- 5.3 VACUUM (FREEZE): xmin у версий остаётся прежним, но помечен замороженным'
VACUUM (FREEZE) freeze_demo;
SELECT c.relfrozenxid, age(c.relfrozenxid) AS table_xid_age
FROM pg_class c WHERE c.relname = 'freeze_demo';
:page_items;
SELECT * FROM pg_visibility_map_summary('freeze_demo');

\echo '--- 5.4 возраст базы и запас до принудительного автовакуума против wraparound'
SELECT datname, age(datfrozenxid) AS xid_age,
       current_setting('autovacuum_freeze_max_age')::bigint - age(datfrozenxid) AS left_to_forced_autovacuum
FROM pg_database WHERE datname = current_database();
