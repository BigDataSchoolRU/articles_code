-- postgres 18.6, прогнано на стенде 2026-11-07
-- Snowflake schema на тех же данных: измерения товара и магазина нормализованы в цепочки
-- товар -> подкатегория -> категория и магазин -> город -> регион.
-- Схема строится из star, поэтому факты и значения атрибутов совпадают строка в строку.
\timing on
DROP SCHEMA IF EXISTS snowflake CASCADE;
CREATE SCHEMA snowflake;

-- Цепочка товара: каждое название категории и подкатегории хранится один раз
CREATE TABLE snowflake.dim_category (
  category_key  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_name text NOT NULL UNIQUE
);
INSERT INTO snowflake.dim_category (category_name)
SELECT DISTINCT category_name FROM star.dim_product ORDER BY 1;

CREATE TABLE snowflake.dim_subcategory (
  subcategory_key  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  subcategory_name text NOT NULL UNIQUE,
  category_key     int NOT NULL REFERENCES snowflake.dim_category
);
INSERT INTO snowflake.dim_subcategory (subcategory_name, category_key)
SELECT DISTINCT p.subcategory_name, c.category_key
FROM star.dim_product p JOIN snowflake.dim_category c USING (category_name)
ORDER BY 1;

CREATE TABLE snowflake.dim_product (
  product_key     int PRIMARY KEY,
  product_code    text NOT NULL UNIQUE,
  product_name    text NOT NULL,
  subcategory_key int NOT NULL REFERENCES snowflake.dim_subcategory
);
INSERT INTO snowflake.dim_product
SELECT p.product_key, p.product_code, p.product_name, s.subcategory_key
FROM star.dim_product p JOIN snowflake.dim_subcategory s USING (subcategory_name);

-- Цепочка магазина
CREATE TABLE snowflake.dim_region (
  region_key  int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  region_name text NOT NULL UNIQUE
);
INSERT INTO snowflake.dim_region (region_name)
SELECT DISTINCT region_name FROM star.dim_store ORDER BY 1;

CREATE TABLE snowflake.dim_city (
  city_key   int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  city_name  text NOT NULL UNIQUE,
  region_key int NOT NULL REFERENCES snowflake.dim_region
);
INSERT INTO snowflake.dim_city (city_name, region_key)
SELECT DISTINCT s.city_name, r.region_key
FROM star.dim_store s JOIN snowflake.dim_region r USING (region_name)
ORDER BY 1;

CREATE TABLE snowflake.dim_store (
  store_key  int PRIMARY KEY,
  store_name text NOT NULL,
  city_key   int NOT NULL REFERENCES snowflake.dim_city
);
INSERT INTO snowflake.dim_store
SELECT s.store_key, s.store_name, c.city_key
FROM star.dim_store s JOIN snowflake.dim_city c USING (city_name);

-- Дата и покупатель не нормализуются: в них нет иерархии, которую стоило бы выносить
CREATE TABLE snowflake.dim_date (LIKE star.dim_date INCLUDING ALL);
INSERT INTO snowflake.dim_date SELECT * FROM star.dim_date;
CREATE TABLE snowflake.dim_customer (LIKE star.dim_customer INCLUDING ALL);
INSERT INTO snowflake.dim_customer SELECT * FROM star.dim_customer;

-- Факт тот же самый: снежинка меняет только измерения
CREATE TABLE snowflake.fact_sales (
  date_key     int NOT NULL,
  product_key  int NOT NULL,
  store_key    int NOT NULL,
  customer_key int NOT NULL,
  quantity     smallint NOT NULL,
  amount       numeric(10,2) NOT NULL
);
INSERT INTO snowflake.fact_sales SELECT * FROM star.fact_sales;

-- Внешние ключи ставятся после загрузки: одна проверка всей таблицы вместо четырёх поисков на каждую строку
ALTER TABLE snowflake.fact_sales
  ADD FOREIGN KEY (date_key)     REFERENCES snowflake.dim_date,
  ADD FOREIGN KEY (product_key)  REFERENCES snowflake.dim_product,
  ADD FOREIGN KEY (store_key)    REFERENCES snowflake.dim_store,
  ADD FOREIGN KEY (customer_key) REFERENCES snowflake.dim_customer;

VACUUM (ANALYZE) snowflake.dim_category, snowflake.dim_subcategory, snowflake.dim_product,
  snowflake.dim_region, snowflake.dim_city, snowflake.dim_store,
  snowflake.dim_date, snowflake.dim_customer, snowflake.fact_sales;
\timing off

-- Сколько таблиц в каждой схеме, сколько строк и места занимает каждая (с индексами)
SELECT n.nspname AS "схема", c.relname AS "таблица",
       (xpath('/row/n/text()', query_to_xml(
          format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text::bigint AS "строк",
       pg_size_pretty(pg_total_relation_size(c.oid)) AS "размер"
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('star', 'snowflake') AND c.relkind = 'r'
ORDER BY 1 DESC, 2;

-- Итог по измерениям товара и магазина, то есть по тому, чем схемы отличаются
SELECT n.nspname AS "схема", count(*) AS "таблиц",
       pg_size_pretty(sum(pg_total_relation_size(c.oid))) AS "размер вместе с индексами"
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('star', 'snowflake') AND c.relkind = 'r'
  AND c.relname IN ('dim_product','dim_subcategory','dim_category','dim_store','dim_city','dim_region')
GROUP BY 1 ORDER BY 1 DESC;
