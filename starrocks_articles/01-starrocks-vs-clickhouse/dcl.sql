-- Код к статье "StarRocks против ClickHouse: сравнение архитектур для аналитики"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-vs-clickhouse-analytics-architecture/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- StarRocks DCL, протестировано для 3.5.0
CREATE USER 'analyst'@'%' IDENTIFIED BY 'Str0ngPass';
GRANT SELECT ON shop.* TO 'analyst'@'%';
SHOW GRANTS FOR 'analyst'@'%';

-- ClickHouse DCL, протестировано для 26.3 LTS
CREATE USER analyst IDENTIFIED BY 'Str0ngPass';
GRANT SELECT ON shop.* TO analyst;
SHOW GRANTS FOR analyst;
