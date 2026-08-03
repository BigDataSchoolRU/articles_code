-- Код к статье "Федерация StarRocks и ClickHouse: гибридное хранилище"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-clickhouse-federation/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- ============================================================
-- federation.sql
-- Гибридное хранилище: федерация StarRocks и ClickHouse.
-- StarRocks вычислительный слой, ClickHouse холодное хранилище.
-- Стенд из статьи 1: обе базы содержат схему shop.
-- Проверено под StarRocks 3.5.0, ClickHouse 26.3, драйвер clickhouse-jdbc 0.4.6.
-- ВАЖНО про версию драйвера. Берём именно 0.4.6 (V1).
-- Новый V2 (0.7+, 0.9.x) запрещает setAutoCommit(false), который вызывает
-- пул StarRocks, и каталог падает с SQLFeatureNotSupportedException.
-- ============================================================

-- ------------------------------------------------------------
-- ШАГ 1. Сторона ClickHouse. Убеждаемся, что таблица-источник есть.
-- Большая холодная order_items уже загружена в статье 1, она и будет
-- играть роль холодного хранилища. Запуск через клиент в контейнере.
-- ------------------------------------------------------------
-- docker exec -it clickhouse clickhouse-client --user default --password Str0ngPass --query \
--   "SELECT count() FROM shop.order_items"

-- ------------------------------------------------------------
-- ШАГ 2. Сторона StarRocks. Создаём внешний JDBC-каталог к ClickHouse.
-- FE и BE скачивают драйвер по driver_url, нужен доступ в сеть до Maven
-- или свой HTTP с этим jar. Хост clickhouse это имя сервиса в docker-compose.
-- ------------------------------------------------------------
CREATE EXTERNAL CATALOG clickhouse_catalog
PROPERTIES (
    "type" = "jdbc",
    "user" = "default",
    "password" = "Str0ngPass",
    -- compress=false обязателен, иначе clickhouse-jdbc падает с "Magic is not correct"
    "jdbc_uri" = "jdbc:clickhouse://clickhouse:8123?compress=false",
    "driver_url" = "https://repo1.maven.org/maven2/com/clickhouse/clickhouse-jdbc/0.9.4/clickhouse-jdbc-0.9.4-all.jar",
    "driver_class" = "com.clickhouse.jdbc.ClickHouseDriver"
);

-- ------------------------------------------------------------
-- ШАГ 3. Осматриваем ClickHouse через каталог, не покидая StarRocks.
-- ------------------------------------------------------------
SHOW CATALOGS;
SET CATALOG clickhouse_catalog;
SHOW DATABASES;
SHOW TABLES FROM clickhouse_catalog.shop;
-- вернуться к локальным таблицам StarRocks
SET CATALOG default_catalog;

-- ------------------------------------------------------------
-- ШАГ 4. Кросс-системный запрос.
-- Локальная orders в StarRocks джойнится с холодной order_items в ClickHouse.
-- Полные имена вида catalog.database.table указывают, где лежит таблица.
-- ------------------------------------------------------------
SELECT
    o.status,
    COUNT(*)          AS items_cnt,
    SUM(ci.quantity)  AS total_qty
FROM default_catalog.shop.orders o
JOIN clickhouse_catalog.shop.order_items ci ON o.order_id = ci.order_id
WHERE o.order_date >= '2025-04-01'
  AND o.status = 'paid'
  AND ci.quantity >= 8
GROUP BY o.status;

-- ------------------------------------------------------------
-- ШАГ 5. Predicate Pushdown.
-- Смотрим план. Предикат ci.quantity >= 8 должен уехать на сторону
-- ClickHouse, чтобы он отфильтровал строки до передачи по сети.
-- В плане у скана внешней таблицы ищи проброшенное условие quantity >= 8.
-- ------------------------------------------------------------
EXPLAIN
SELECT
    o.status,
    COUNT(*)          AS items_cnt,
    SUM(ci.quantity)  AS total_qty
FROM default_catalog.shop.orders o
JOIN clickhouse_catalog.shop.order_items ci ON o.order_id = ci.order_id
WHERE o.order_date >= '2025-04-01'
  AND o.status = 'paid'
  AND ci.quantity >= 8
GROUP BY o.status;

-- ------------------------------------------------------------
-- ШАГ 6. Очистка.
-- ------------------------------------------------------------
-- DROP CATALOG clickhouse_catalog;
