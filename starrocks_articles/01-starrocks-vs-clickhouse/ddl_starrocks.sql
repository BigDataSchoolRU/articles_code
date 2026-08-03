-- Код к статье "StarRocks против ClickHouse: сравнение архитектур для аналитики"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-vs-clickhouse-analytics-architecture/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- протестировано для StarRocks 3.5.0
CREATE DATABASE shop;
USE shop;

CREATE TABLE customers (
    customer_id BIGINT,
    name        VARCHAR(64),
    region_id   INT,
    signup_date DATE
) DUPLICATE KEY(customer_id)
DISTRIBUTED BY HASH(customer_id) BUCKETS 16;

CREATE TABLE products (
    product_id  BIGINT,
    name        VARCHAR(64),
    category_id INT,
    price       DECIMAL(10,2)
) DUPLICATE KEY(product_id)
DISTRIBUTED BY HASH(product_id) BUCKETS 16;

CREATE TABLE orders (
    order_id    BIGINT,
    customer_id BIGINT,
    order_date  DATE,
    status      VARCHAR(16)
) DUPLICATE KEY(order_id)
DISTRIBUTED BY HASH(order_id) BUCKETS 48;

CREATE TABLE order_items (
    item_id    BIGINT,
    order_id   BIGINT,
    product_id BIGINT,
    quantity   INT
) DUPLICATE KEY(item_id)
DISTRIBUTED BY HASH(order_id) BUCKETS 96;
