-- Код к статье "StarRocks против ClickHouse: сравнение архитектур для аналитики"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-vs-clickhouse-analytics-architecture/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- протестировано для ClickHouse 26.3 LTS
CREATE DATABASE shop;

CREATE TABLE shop.customers (
    customer_id UInt64,
    name        String,
    region_id   UInt16,
    signup_date Date
) ENGINE = MergeTree ORDER BY customer_id;

CREATE TABLE shop.products (
    product_id  UInt64,
    name        String,
    category_id UInt16,
    price       Decimal(10,2)
) ENGINE = MergeTree ORDER BY product_id;

CREATE TABLE shop.orders (
    order_id    UInt64,
    customer_id UInt64,
    order_date  Date,
    status      String
) ENGINE = MergeTree ORDER BY order_id;

CREATE TABLE shop.order_items (
    item_id    UInt64,
    order_id   UInt64,
    product_id UInt64,
    quantity   UInt32
) ENGINE = MergeTree ORDER BY order_id;
