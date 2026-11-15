-- Apache Cloudberry 2.2.0-incubating, демо-кластер gpdemo с 3 primary-сегментами, прогнано на стенде 2026-11-15
-- Как ключ распределения раскладывает строки по сегментам и откуда берётся перекос.

DROP TABLE IF EXISTS orders_by_id, orders_by_status, orders_random, regions;

-- Миллион заказов, ключ распределения order_id: хеш от уникального значения.
CREATE TABLE orders_by_id (
    order_id    bigint,
    customer_id int,
    status      text,
    amount      numeric(10,2)
) DISTRIBUTED BY (order_id);

-- 80% заказов delivered, 10% shipped, 10% cancelled.
INSERT INTO orders_by_id
SELECT g,
       (g % 100000) + 1,
       CASE WHEN g % 10 < 8 THEN 'delivered' WHEN g % 10 = 8 THEN 'shipped' ELSE 'cancelled' END,
       (g % 1000) / 10.0
FROM generate_series(1, 1000000) AS g;

-- Те же строки, но ключ распределения это низкокардинальный статус: три значения на весь миллион.
CREATE TABLE orders_by_status (LIKE orders_by_id) DISTRIBUTED BY (status);
INSERT INTO orders_by_status SELECT * FROM orders_by_id;

-- Без ключа: строки раскладываются по кругу, перекоса нет, но и JOIN по ключу не будет локальным.
CREATE TABLE orders_random (LIKE orders_by_id) DISTRIBUTED RANDOMLY;
INSERT INTO orders_random SELECT * FROM orders_by_id;

-- Политика распределения из каталога: p = по хешу ключа или случайно (distkey пустой), r = копия на каждом сегменте.
SELECT localoid::regclass AS table_name, policytype, distkey
FROM gp_distribution_policy
WHERE localoid IN ('orders_by_id'::regclass, 'orders_by_status'::regclass, 'orders_random'::regclass)
ORDER BY 1;

-- Сколько строк лежит на каждом сегменте: gp_segment_id это служебная колонка «на каком сегменте строка».
SELECT 'orders_by_id' AS table_name, gp_segment_id, count(*) AS row_count FROM orders_by_id GROUP BY gp_segment_id
UNION ALL
SELECT 'orders_by_status', gp_segment_id, count(*) FROM orders_by_status GROUP BY gp_segment_id
UNION ALL
SELECT 'orders_random', gp_segment_id, count(*) FROM orders_random GROUP BY gp_segment_id
ORDER BY 1, 2;

-- Где оказался каждый статус: одно значение ключа целиком уходит на один сегмент.
SELECT status, gp_segment_id, count(*) AS row_count
FROM orders_by_status
GROUP BY status, gp_segment_id
ORDER BY status;

-- Коэффициент перекоса из gp_toolkit: 0 означает ровное распределение, чем больше, тем хуже.
SELECT skcrelname AS table_name, round(skccoeff, 2) AS skew_coefficient
FROM gp_toolkit.gp_skew_coefficients
WHERE skcrelname IN ('orders_by_id', 'orders_by_status', 'orders_random')
ORDER BY 1;

-- Маленький справочник: DISTRIBUTED REPLICATED держит полную копию на каждом сегменте.
CREATE TABLE regions (
    region_id   int,
    region_name text
) DISTRIBUTED REPLICATED;
INSERT INTO regions VALUES (1, 'North'), (2, 'Center'), (3, 'South');

-- gp_dist_random() читает таблицу на каждом сегменте отдельно, gp_execution_segment() говорит, на каком.
-- Колонки gp_segment_id у реплицированной таблицы нет: строка не принадлежит одному сегменту.
SELECT gp_execution_segment() AS segment, count(*) AS row_count
FROM gp_dist_random('regions')
GROUP BY 1
ORDER BY 1;
