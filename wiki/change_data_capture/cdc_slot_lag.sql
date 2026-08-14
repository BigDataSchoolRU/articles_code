-- PostgreSQL 18.4 (Homebrew), отставание слота репликации, прогон на стенде 2026-08-14
-- запускается после cdc_slot_demo.sql

-- шаг 1: имитируем рабочую нагрузку, пока потребитель молчит
INSERT INTO orders SELECT g, 'клиент ' || g, 'new', g * 1.5
  FROM generate_series(3, 200000) g;

-- шаг 2: ключевая метрика эксплуатации, сколько журнала база держит из-за слота
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained_wal
  FROM pg_replication_slots;

-- шаг 3: потребитель прочитал поток, слот сдвинулся, журнал освободился
SELECT count(*) AS events_read FROM pg_logical_slot_get_changes('cdc_demo_slot', NULL, NULL);
SELECT slot_name,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained_wal
  FROM pg_replication_slots;
