-- Apache Cloudberry 2.2.0-incubating, демо-кластер gpdemo с 3 primary-сегментами, прогнано на стенде 2026-11-15
-- Три формата хранения одной таблицы: строчный heap, колоночный ao_column и гибридный PAX.
-- Запускать после 02_distribution_skew.sql: нужна таблица orders_by_id.

-- Какие методы доступа есть в сборке.
SELECT amname FROM pg_am WHERE amtype = 't' ORDER BY amname;

DROP TABLE IF EXISTS orders_heap, orders_aoco, orders_pax;

-- Строчный heap, как в обычном PostgreSQL.
CREATE TABLE orders_heap (LIKE orders_by_id) DISTRIBUTED BY (order_id);

-- Append-optimized колоночная таблица со сжатием zstd: каждая колонка лежит в своём файле.
CREATE TABLE orders_aoco (LIKE orders_by_id)
USING ao_column WITH (compresstype = zstd, compresslevel = 5)
DISTRIBUTED BY (order_id);

-- PAX: строки группами, внутри группы данные по колонкам, плюс статистика min/max для пропуска групп.
CREATE TABLE orders_pax (LIKE orders_by_id)
USING pax WITH (compresstype = zstd, compresslevel = 5)
DISTRIBUTED BY (order_id);

INSERT INTO orders_heap SELECT * FROM orders_by_id;
INSERT INTO orders_aoco SELECT * FROM orders_by_id;
INSERT INTO orders_pax  SELECT * FROM orders_by_id;

-- Размер на диске: на координаторе функция суммирует размер по всем сегментам.
SELECT c.relname AS table_name, a.amname AS access_method,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_class c
JOIN pg_am a ON a.oid = c.relam
WHERE c.relname IN ('orders_heap', 'orders_aoco', 'orders_pax')
ORDER BY pg_total_relation_size(c.oid) DESC;
