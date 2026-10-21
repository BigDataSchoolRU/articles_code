-- ClickHouse 26.9.23.15, прогнано на стенде 2026-10-21
-- Что происходило со вставками DAG retry_dedup: async или нет, сколько блоков отброшено как дубли
SYSTEM FLUSH LOGS;
SELECT
    tables[1] AS table_name,
    count() AS inserts,
    sum(ProfileEvents['AsyncInsertQuery']) AS async_inserts,
    sum(written_rows) AS sent_rows
FROM system.query_log
WHERE type = 'QueryFinish' AND query_kind = 'Insert' AND table_name LIKE 'demo.events%'
GROUP BY table_name
ORDER BY table_name
FORMAT PrettyCompactMonoBlock;
-- дубли считаются там, где блок реально пишется: в самом INSERT или в сбросе async-буфера
SELECT
    sum(ProfileEvents['DuplicatedInsertedBlocks']) AS duplicated_blocks_total
FROM system.query_log
WHERE type = 'QueryFinish' AND has(tables, 'demo.events_token_async')
FORMAT PrettyCompactMonoBlock;
