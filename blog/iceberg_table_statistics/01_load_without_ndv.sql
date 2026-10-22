-- Trino 484, Iceberg REST-каталог, прогнано на стенде 2026-10-22
-- Грузим TPC-H sf1 в Iceberg и намеренно не собираем NDV при записи.

CREATE SCHEMA IF NOT EXISTS iceberg.tpch;

-- По умолчанию CTAS в Trino сразу пишет Puffin с NDV. Выключаем, чтобы увидеть таблицу
-- только с метриками из манифестов: так выглядит таблица, записанная движком без сбора NDV.
SET SESSION iceberg.collect_extended_statistics_on_write = false;

CREATE TABLE iceberg.tpch.nation   AS SELECT * FROM tpch.sf1.nation;
CREATE TABLE iceberg.tpch.customer AS SELECT * FROM tpch.sf1.customer;
CREATE TABLE iceberg.tpch.orders   AS SELECT * FROM tpch.sf1.orders;
CREATE TABLE iceberg.tpch.lineitem AS SELECT * FROM tpch.sf1.lineitem;

-- distinct_values_count пустой, min/max и nulls_fraction есть: они из манифестов
SHOW STATS FOR iceberg.tpch.orders;
