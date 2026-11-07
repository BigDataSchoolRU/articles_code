-- postgres 18.6, прогнано на стенде 2026-11-07
-- Цена смены атрибута: категорию «Электроника» переименовали в «Электроника и гаджеты».
-- В звезде название повторяется в каждой строке товара, в снежинке хранится один раз.

\echo '--- Звезда: UPDATE по всем товарам категории'
SELECT pg_current_wal_lsn() AS lsn0 \gset
UPDATE star.dim_product SET category_name = 'Электроника и гаджеты' WHERE category_name = 'Электроника';
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), :'lsn0')) AS "WAL на звезде";

\echo '--- Снежинка: UPDATE одной строки справочника категорий'
SELECT pg_current_wal_lsn() AS lsn0 \gset
UPDATE snowflake.dim_category SET category_name = 'Электроника и гаджеты' WHERE category_name = 'Электроника';
SELECT pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), :'lsn0')) AS "WAL на снежинке";

\echo '--- Выручка новой категории за II квартал 2025 в обеих схемах'
SELECT 'star' AS "схема", sum(f.amount) AS revenue
FROM star.fact_sales f
JOIN star.dim_date d ON d.date_key = f.date_key
JOIN star.dim_product p ON p.product_key = f.product_key
WHERE d.year = 2025 AND d.quarter = 2 AND p.category_name = 'Электроника и гаджеты'
UNION ALL
SELECT 'snowflake', sum(f.amount)
FROM snowflake.fact_sales f
JOIN snowflake.dim_date d ON d.date_key = f.date_key
JOIN snowflake.dim_product p ON p.product_key = f.product_key
JOIN snowflake.dim_subcategory sc ON sc.subcategory_key = p.subcategory_key
JOIN snowflake.dim_category cat ON cat.category_key = sc.category_key
WHERE d.year = 2025 AND d.quarter = 2 AND cat.category_name = 'Электроника и гаджеты';
