-- Trino 484, Iceberg REST-каталог, прогнано на стенде 2026-10-22
-- Удаляем NDV, который записал Trino, чтобы статистику пересчитал Spark.

ALTER TABLE iceberg.tpch.nation   EXECUTE drop_extended_stats;
ALTER TABLE iceberg.tpch.customer EXECUTE drop_extended_stats;
ALTER TABLE iceberg.tpch.orders   EXECUTE drop_extended_stats;
ALTER TABLE iceberg.tpch.lineitem EXECUTE drop_extended_stats;

-- distinct_values_count снова пустой
SHOW STATS FOR iceberg.tpch.orders;
