-- postgres 18.6, прогнано на стенде 2026-11-07
-- Star schema: таблица фактов продаж и четыре денормализованных измерения.
-- Гранулярность факта: одна строка на позицию чека (дата, товар, магазин, покупатель).
-- Данные воспроизводимы: random() идёт от фиксированного setseed.
\timing on
DROP SCHEMA IF EXISTS star CASCADE;
CREATE SCHEMA star;

-- Измерение даты: ключ в виде ГГГГММДД, атрибуты для фильтров и группировки
CREATE TABLE star.dim_date (
  date_key    int PRIMARY KEY,
  full_date   date NOT NULL,
  year        smallint NOT NULL,
  quarter     smallint NOT NULL,
  month       smallint NOT NULL,
  iso_dow     smallint NOT NULL
);
INSERT INTO star.dim_date
SELECT to_char(d, 'YYYYMMDD')::int, d, extract(year FROM d), extract(quarter FROM d),
       extract(month FROM d), extract(isodow FROM d)
FROM generate_series(date '2024-01-01', date '2025-12-31', interval '1 day') AS g(ts),
     LATERAL (SELECT ts::date AS d) x;

-- Измерение товара: иерархия товар -> подкатегория -> категория лежит в одной строке
CREATE TABLE star.dim_product (
  product_key      int PRIMARY KEY,         -- суррогатный ключ хранилища
  product_code     text NOT NULL UNIQUE,    -- естественный ключ из учётной системы
  product_name     text NOT NULL,
  subcategory_name text NOT NULL,
  category_name    text NOT NULL
);
INSERT INTO star.dim_product
SELECT n,
       format('SKU-%s', lpad(n::text, 5, '0')),
       format('Товар %s', n),
       format('%s: группа %s', cat[1 + (n - 1) % 12], 1 + ((n - 1) / 12) % 10),
       cat[1 + (n - 1) % 12]
FROM generate_series(1, 12000) AS n,
     (SELECT ARRAY['Электроника','Бытовая техника','Одежда','Обувь','Книги','Игрушки',
                   'Спорт','Дом и сад','Красота','Продукты','Автотовары','Зоотовары'] AS cat) c;

-- Измерение магазина: иерархия магазин -> город -> регион тоже в одной строке
CREATE TABLE star.dim_store (
  store_key   int PRIMARY KEY,
  store_name  text NOT NULL,
  city_name   text NOT NULL,
  region_name text NOT NULL
);
INSERT INTO star.dim_store
SELECT n,
       format('Магазин %s', n),
       format('Город %s', lpad((1 + (n - 1) % 40)::text, 2, '0')),
       reg[1 + ((n - 1) % 40) % 8]
FROM generate_series(1, 400) AS n,
     (SELECT ARRAY['Центральный','Северо-Западный','Южный','Северо-Кавказский',
                   'Приволжский','Уральский','Сибирский','Дальневосточный'] AS reg) r;

-- Измерение покупателя: в выборке не участвует, нужно для опыта с удалением JOIN
CREATE TABLE star.dim_customer (
  customer_key  int PRIMARY KEY,
  customer_name text NOT NULL,
  segment       text NOT NULL
);
INSERT INTO star.dim_customer
SELECT n, format('Покупатель %s', n), (ARRAY['розница','опт','корпоративный'])[1 + n % 3]
FROM generate_series(1, 100000) AS n;

-- Таблица фактов: только ключи измерений и аддитивные меры
CREATE TABLE star.fact_sales (
  date_key     int NOT NULL,
  product_key  int NOT NULL,
  store_key    int NOT NULL,
  customer_key int NOT NULL,
  quantity     smallint NOT NULL,
  amount       numeric(10,2) NOT NULL
);
-- setseed делает random() воспроизводимым: при каждом прогоне на чистой базе выходят те же 2 млн строк
SELECT setseed(0.42);
INSERT INTO star.fact_sales
SELECT to_char(date '2024-01-01' + random(0, 730), 'YYYYMMDD')::int,
       random(1, 12000),
       random(1, 400),
       random(1, 100000),
       random(1, 5),
       random(500, 99999) / 100.0
FROM generate_series(1, 2000000);

-- Внешние ключи ставятся после загрузки: одна проверка всей таблицы вместо четырёх поисков на каждую строку
ALTER TABLE star.fact_sales
  ADD FOREIGN KEY (date_key)     REFERENCES star.dim_date,
  ADD FOREIGN KEY (product_key)  REFERENCES star.dim_product,
  ADD FOREIGN KEY (store_key)    REFERENCES star.dim_store,
  ADD FOREIGN KEY (customer_key) REFERENCES star.dim_customer;

VACUUM (ANALYZE) star.dim_date, star.dim_product, star.dim_store, star.dim_customer, star.fact_sales;
\timing off

SELECT 'star.fact_sales' AS "таблица", count(*) AS "строк" FROM star.fact_sales
UNION ALL SELECT 'star.dim_product', count(*) FROM star.dim_product
UNION ALL SELECT 'star.dim_store', count(*) FROM star.dim_store;
