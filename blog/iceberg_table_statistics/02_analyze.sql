-- Trino 484, Iceberg REST-каталог, прогнано на стенде 2026-10-22
-- ANALYZE считает NDV по всем колонкам и пишет Puffin-файл к текущему снапшоту.

ANALYZE iceberg.tpch.nation;
ANALYZE iceberg.tpch.customer;
ANALYZE iceberg.tpch.orders;
ANALYZE iceberg.tpch.lineitem;

-- Колонка distinct_values_count заполнена
SHOW STATS FOR iceberg.tpch.orders;

-- NDV это оценка по theta sketch. Сверяем с точным подсчётом
SELECT count(DISTINCT custkey) AS exact_custkey,
       count(DISTINCT clerk)   AS exact_clerk
FROM iceberg.tpch.orders;
