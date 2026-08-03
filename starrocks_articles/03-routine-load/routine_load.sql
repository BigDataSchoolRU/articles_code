-- Код к статье "Потоковая загрузка из Apache Kafka в StarRocks через Routine Load"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-routine-load-kafka/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- протестировано для StarRocks 3.5.0
-- Потоковая загрузка JSON-событий заказов из Kafka в StarRocks через Routine Load.
-- Kafka 3.9.2, брокеры 10.140.0.91-93:9092, топик orders.
-- Предусловие: BE-нода StarRocks должна иметь сетевой доступ к брокерам.

USE shop;

-- ------------------------------------------------------------
-- Целевая таблица. Модель PRIMARY KEY даёт нативный UPSERT:
-- повторное событие с тем же order_id обновит строку, а не задвоит.
-- Именно это нужно для real-time витрины из потока.
-- ------------------------------------------------------------
CREATE TABLE orders_rt (
    order_id    BIGINT,
    customer_id BIGINT,
    region_id   INT,
    order_date  DATE,
    status      VARCHAR(16),
    amount      DECIMAL(10,2),
    event_time  DATETIME
) PRIMARY KEY(order_id)
DISTRIBUTED BY HASH(order_id) BUCKETS 16;

-- ------------------------------------------------------------
-- Задача Routine Load.
-- JSONPaths мапят вложенные поля customer.id и customer.region
-- в плоские колонки customer_id и region_id.
-- Порядок в COLUMNS соответствует порядку в jsonpaths.
-- ------------------------------------------------------------
CREATE ROUTINE LOAD shop.orders_stream ON orders_rt
COLUMNS(order_id, customer_id, region_id, order_date, status, amount, event_time)
PROPERTIES (
    "format" = "json",
    "jsonpaths" = "[\"$.order_id\",\"$.customer.id\",\"$.customer.region\",\"$.order_date\",\"$.status\",\"$.amount\",\"$.event_time\"]",
    "desired_concurrent_number" = "3",
    "max_batch_interval" = "10",
    "max_error_number" = "100"
)
FROM KAFKA (
    "kafka_broker_list" = "10.140.0.91:9092,10.140.0.92:9092,10.140.0.93:9092",
    "kafka_topic" = "orders",
    "property.kafka_default_offsets" = "OFFSET_BEGINNING"
);

-- ------------------------------------------------------------
-- Мониторинг и управление задачей.
-- ------------------------------------------------------------
-- Статус задачи: State должен быть RUNNING, смотри поля
-- Progress (offset по партициям) и Lag (отставание консьюмера).
SHOW ROUTINE LOAD FOR shop.orders_stream\G

-- Текущие подзадачи по партициям.
SHOW ROUTINE LOAD TASK WHERE JobName = "orders_stream"\G

-- Пауза, возобновление, остановка.
-- PAUSE ROUTINE LOAD FOR shop.orders_stream;
-- RESUME ROUTINE LOAD FOR shop.orders_stream;
-- STOP ROUTINE LOAD FOR shop.orders_stream;

-- Проверка, что данные едут.
SELECT count(*) FROM shop.orders_rt;
SELECT * FROM shop.orders_rt ORDER BY event_time DESC LIMIT 10;
