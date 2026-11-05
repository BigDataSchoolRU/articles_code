-- postgres 18.6, прогнано на стенде 2026-11-05: брошенный слот репликации держит сегменты pg_wal
\pset footer off
SHOW max_wal_size;
SHOW max_slot_wal_keep_size;

CREATE TEMP VIEW wal_dir AS
SELECT count(*) AS segments, pg_size_pretty(sum(size)) AS pg_wal_size FROM pg_ls_waldir();

DROP TABLE IF EXISTS wal_filler;
CREATE TABLE wal_filler (id int, pad text);

\echo '--- 1. без слота: нагрузка на журнал, контрольная точка, сегменты переиспользуются'
SELECT pg_current_wal_lsn() AS gen_start \gset
INSERT INTO wal_filler SELECT g, repeat('x', 500) FROM generate_series(1, 300000) g;
TRUNCATE wal_filler;
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), :'gen_start')) AS wal_generated;
CHECKPOINT;
SELECT * FROM wal_dir;

\echo '--- 2. физический слот, к которому никто не подключился'
SELECT slot_name, lsn FROM pg_create_physical_replication_slot('lagging_replica', true);
SELECT pg_current_wal_lsn() AS gen_start \gset
INSERT INTO wal_filler SELECT g, repeat('x', 500) FROM generate_series(1, 300000) g;
TRUNCATE wal_filler;
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), :'gen_start')) AS wal_generated;
CHECKPOINT;
SELECT * FROM wal_dir;
SELECT slot_name, active, restart_lsn, wal_status, safe_wal_size
FROM pg_replication_slots;

\echo '--- 3. потолок для слотов: max_slot_wal_keep_size = 32MB'
ALTER SYSTEM SET max_slot_wal_keep_size = '32MB';
SELECT pg_reload_conf();
SELECT pg_sleep(1) \g /dev/null
CHECKPOINT;
SELECT * FROM wal_dir;
SELECT slot_name, active, restart_lsn, wal_status, invalidation_reason
FROM pg_replication_slots;

-- уборка: слот и настройка возвращаются в исходное
SELECT pg_drop_replication_slot('lagging_replica');
ALTER SYSTEM RESET max_slot_wal_keep_size;
SELECT pg_reload_conf();
DROP TABLE wal_filler;
