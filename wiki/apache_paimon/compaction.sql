-- Apache Paimon 2.1.0: paimon-spark-4.0_2.13 2.1.0 на Spark 4.0.4, прогнано на стенде 2026-11-15
-- Таблицы записаны pypaimon (pk_table_demo.py и merge_engine_demo.py), компакцию делает Spark.
USE paimon;

-- 1. До компакции: все файлы на уровне 0 LSM-дерева, по файлу на коммит в каждом бакете
SELECT 'orders до компакции' AS stage, bucket, level, record_count
FROM shop.`orders$files` ORDER BY bucket, level, record_count;

-- 2. Компакция сливает файлы бакета в один отсортированный файл на верхнем уровне
CALL sys.compact(table => 'shop.orders');

SELECT 'orders после компакции' AS stage, bucket, level, record_count
FROM shop.`orders$files` ORDER BY bucket, level;

-- 3. Компакция это отдельный снапшот вида COMPACT, данные таблицы не меняются
SELECT snapshot_id, commit_kind, total_record_count, delta_record_count, changelog_record_count
FROM shop.`orders$snapshots` ORDER BY snapshot_id;

SELECT * FROM shop.orders ORDER BY order_id;

-- 4. first-row: пакетное чтение видит строку только после компакции
SELECT 'first-row до компакции, строк' AS stage, count(*) FROM engines.orders_first_row;
CALL sys.compact(table => 'engines.orders_first_row');
SELECT 'first-row после компакции' AS stage, * FROM engines.orders_first_row;
