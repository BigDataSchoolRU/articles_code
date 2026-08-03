-- Код к статье "Асинхронные материализованные представления в StarRocks вместо ETL"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-async-materialized-views/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- ============================================================
-- mv_demo.sql
-- Асинхронные материализованные представления в StarRocks вместо ETL.
-- Стенд shop из предыдущих статей. Проверено под StarRocks 3.5.0.
-- Подключение: mysql -h 127.0.0.1 -P 9030 -u root, затем USE shop.
-- Идём по шагам, между ними смотрим статус.
-- ============================================================

USE shop;

-- ------------------------------------------------------------
-- ШАГ 1. ODS слой. Партиционированная таблица сырых заказов.
-- Партиционирование по месяцу нужно, чтобы MV обновлялась
-- инкрементально, по одной партиции, а не целиком.
-- ------------------------------------------------------------
CREATE TABLE ods_orders (
    order_id    BIGINT,
    customer_id BIGINT,
    order_date  DATE,
    status      VARCHAR(16)
)
DUPLICATE KEY(order_id)
PARTITION BY date_trunc('month', order_date)
DISTRIBUTED BY HASH(order_id) BUCKETS 48;

-- Наполняем ODS из уже загруженной таблицы orders.
INSERT INTO ods_orders
SELECT order_id, customer_id, order_date, status FROM orders;

-- Проверяем, что партиции создались автоматически по месяцам.
SHOW PARTITIONS FROM ods_orders;

-- ------------------------------------------------------------
-- ШАГ 2. Асинхронное материализованное представление.
-- Витрина выручки по дате, региону и категории. Внутри джойн
-- четырёх таблиц и агрегация. Обновляется по расписанию,
-- раз в 10 минут, а не на каждую вставку.
-- Партиционирование MV по месяцу выравнивается с ods_orders.
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_daily_revenue
PARTITION BY date_trunc('month', order_date)
DISTRIBUTED BY HASH(region_id) BUCKETS 8
REFRESH ASYNC EVERY (INTERVAL 10 MINUTE)
AS
SELECT
    o.order_date,
    c.region_id,
    p.category_id,
    SUM(oi.quantity * p.price) AS revenue,
    COUNT(DISTINCT o.order_id) AS orders_cnt
FROM order_items oi
JOIN ods_orders o ON oi.order_id = o.order_id
JOIN products   p ON oi.product_id = p.product_id
JOIN customers  c ON o.customer_id = c.customer_id
GROUP BY o.order_date, c.region_id, p.category_id;

-- ------------------------------------------------------------
-- ШАГ 3. Смотрим состояние MV и историю обновлений.
-- ------------------------------------------------------------
-- Список MV, колонка last_refresh_state показывает результат
-- последнего обновления, is_active показывает, живо ли MV.
SELECT table_name, is_active, last_refresh_state, last_refresh_finished_time
FROM information_schema.materialized_views
WHERE table_schema = 'shop';

-- Компактный статус.
SHOW MATERIALIZED VIEWS FROM shop\G

-- История запусков обновления. Каждая строка это один refresh,
-- виден STATE (SUCCESS, FAILED, RUNNING) и время.
SELECT task_name, state, create_time, finish_time, error_message
FROM information_schema.task_runs
ORDER BY create_time DESC
LIMIT 10;

-- ------------------------------------------------------------
-- ШАГ 4. Читаем витрину как обычную таблицу.
-- Запрос к MV идёт по готовым агрегатам, без пересчёта джойна.
-- ------------------------------------------------------------
SELECT region_id, category_id, SUM(revenue) AS revenue
FROM mv_daily_revenue
WHERE order_date >= '2025-04-01'
GROUP BY region_id, category_id
ORDER BY revenue DESC
LIMIT 20;

-- ------------------------------------------------------------
-- ШАГ 5. Инкрементальное обновление по партиции.
-- Меняем данные только одного месяца в ODS и смотрим, что
-- StarRocks пересчитает лишь соответствующую партицию MV.
-- ------------------------------------------------------------
-- Досыпаем новые заказы в один месяц.
INSERT INTO ods_orders VALUES
  (999000001, 12345, '2025-06-15', 'paid'),
  (999000002, 12346, '2025-06-16', 'paid');

-- Принудительно обновляем только партицию июня, синхронно, чтобы дождаться.
REFRESH MATERIALIZED VIEW shop.mv_daily_revenue
PARTITION START ("2025-06-01") END ("2025-07-01")
WITH SYNC MODE;

-- Список пересчитанных партиций лежит в EXTRA_MESSAGE, а не в имени задачи.
-- Имя task_name одинаковое у всех прогонов, это идентификатор самого MV.
-- Смотри ключ mvPartitionsToRefresh в JSON поля extra_message.
SELECT state, create_time, finish_time, extra_message
FROM information_schema.task_runs
ORDER BY create_time DESC
LIMIT 5;

-- Полная строка последнего запуска со всеми полями.
SELECT * FROM information_schema.task_runs
ORDER BY create_time DESC LIMIT 1\G

-- ------------------------------------------------------------
-- ШАГ 6. Эмуляция сбоя и восстановление.
-- Если обновление упало, MV остаётся с данными прошлого успешного
-- прогона, витрина не бьётся. Причину смотрим в error_message,
-- затем повторяем обновление принудительно.
-- ------------------------------------------------------------
-- Полное принудительное обновление всех партиций.
REFRESH MATERIALIZED VIEW shop.mv_daily_revenue WITH SYNC MODE;

-- Приостановить и возобновить автоматическое обновление по расписанию.
-- ALTER MATERIALIZED VIEW shop.mv_daily_revenue INACTIVE;
-- ALTER MATERIALIZED VIEW shop.mv_daily_revenue ACTIVE;

-- ------------------------------------------------------------
-- ШАГ 7. Очистка.
-- ------------------------------------------------------------
-- DROP MATERIALIZED VIEW shop.mv_daily_revenue;
-- DROP TABLE shop.ods_orders;
