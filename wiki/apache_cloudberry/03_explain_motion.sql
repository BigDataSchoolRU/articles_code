-- Apache Cloudberry 2.2.0-incubating, демо-кластер gpdemo с 3 primary-сегментами, прогнано на стенде 2026-11-15
-- План распределённого запроса: когда JOIN локальный, а когда строки едут между сегментами через Motion.
-- Запускать после 02_distribution_skew.sql: нужны таблицы orders_by_id и regions.

DROP TABLE IF EXISTS customers, orders_by_customer;

-- Клиенты распределены по customer_id.
CREATE TABLE customers (
    customer_id int,
    region_id   int,
    name        text
) DISTRIBUTED BY (customer_id);
INSERT INTO customers
SELECT g, g % 3 + 1, 'customer_' || g
FROM generate_series(1, 100000) AS g;

-- Те же заказы, что в orders_by_id, но с ключом распределения customer_id, как у customers.
CREATE TABLE orders_by_customer (LIKE orders_by_id) DISTRIBUTED BY (customer_id);
INSERT INTO orders_by_customer SELECT * FROM orders_by_id;

ANALYZE customers;
ANALYZE orders_by_id;
ANALYZE orders_by_customer;
ANALYZE regions;

-- 1. JOIN по ключу распределения обеих таблиц: строки одного клиента уже лежат на одном сегменте.
--    Пересылка нужна только в конце, чтобы собрать частичные суммы на координаторе (Gather Motion).
EXPLAIN (COSTS OFF)
SELECT count(*), sum(o.amount)
FROM orders_by_customer o
JOIN customers c ON c.customer_id = o.customer_id;

-- 2. Заказы распределены по order_id, а JOIN идёт по customer_id: одну из сторон надо переслать.
EXPLAIN (COSTS OFF)
SELECT count(*), sum(o.amount)
FROM orders_by_id o
JOIN customers c ON c.customer_id = o.customer_id;

-- 3. Тот же запрос с классическим планировщиком Postgres вместо GPORCA.
SET optimizer = off;
EXPLAIN (COSTS OFF)
SELECT count(*), sum(o.amount)
FROM orders_by_id o
JOIN customers c ON c.customer_id = o.customer_id;
RESET optimizer;

-- 4. JOIN с реплицированным справочником: копия regions есть на каждом сегменте, пересылать нечего.
EXPLAIN (COSTS OFF)
SELECT r.region_name, count(*)
FROM customers c
JOIN regions r ON r.region_id = c.region_id
GROUP BY r.region_name;

-- 5. Точечный запрос по ключу распределения: координатор знает сегмент и шлёт запрос только ему (Gather Motion 1:1).
EXPLAIN (COSTS OFF)
SELECT * FROM orders_by_id WHERE order_id = 42;

-- 6. Реальное выполнение запроса 2: сколько строк прошло через каждый Motion.
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT count(*), sum(o.amount)
FROM orders_by_id o
JOIN customers c ON c.customer_id = o.customer_id;

-- Результат одинаков при любом ключе распределения: меняется только путь данных.
SELECT 'by customer_id' AS layout, count(*), sum(o.amount)
FROM orders_by_customer o JOIN customers c ON c.customer_id = o.customer_id
UNION ALL
SELECT 'by order_id', count(*), sum(o.amount)
FROM orders_by_id o JOIN customers c ON c.customer_id = o.customer_id;
