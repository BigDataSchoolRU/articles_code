-- Trino 484, Iceberg REST-каталог, прогнано на стенде 2026-10-22
-- Trino читает Puffin, который записал Spark: NDV есть только у посчитанных колонок.

SHOW STATS FOR iceberg.tpch.orders;
