-- postgres 18.6, прогнано на стенде 2026-11-05: запись и fsync журнала по типам процессов (pg_stat_io, с PostgreSQL 18)
\pset footer off
SELECT pg_stat_force_next_flush() \g /dev/null
SELECT backend_type, context, writes, fsyncs
FROM pg_stat_io
WHERE object = 'wal' AND (writes > 0 OR fsyncs > 0)
ORDER BY backend_type, context;
