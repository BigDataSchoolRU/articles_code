-- Код к статье "StarRocks против ClickHouse: сравнение архитектур для аналитики"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-vs-clickhouse-analytics-architecture/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- Аналитический запрос с четырьмя JOIN. Одинаковый смысл для StarRocks и ClickHouse.
-- Выручка по регионам и категориям за последний квартал.
SELECT
    c.region_id,
    p.category_id,
    SUM(oi.quantity * p.price) AS revenue,
    COUNT(DISTINCT o.order_id) AS orders_cnt
FROM order_items oi
JOIN orders   o  ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
JOIN products  p ON oi.product_id = p.product_id
WHERE o.order_date >= '2025-04-01'
  AND o.status = 'paid'
GROUP BY c.region_id, p.category_id
ORDER BY revenue DESC
LIMIT 50;

-- StarRocks. Сбор статистики перед запуском, чтобы CBO построил корректный план.
-- ANALYZE TABLE order_items;
-- ANALYZE TABLE orders;
-- ANALYZE TABLE customers;
-- ANALYZE TABLE products;
