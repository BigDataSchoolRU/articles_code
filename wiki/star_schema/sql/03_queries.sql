-- postgres 18.6, прогнано на стенде 2026-11-07
-- Одна бизнес-выборка «выручка по категории и региону за II квартал 2025» на звезде и на снежинке.
-- Сравниваем результат, план (число JOIN), время выполнения и время планирования.

-- Тексты запросов лежат в таблице, чтобы планы и замеры шли ровно по тому же SQL
CREATE TEMP TABLE demo_queries (name text PRIMARY KEY, sql text NOT NULL);
INSERT INTO demo_queries VALUES
('star', $q$
SELECT p.category_name, s.region_name, sum(f.amount) AS revenue, sum(f.quantity) AS units
FROM star.fact_sales f
JOIN star.dim_date    d ON d.date_key    = f.date_key
JOIN star.dim_product p ON p.product_key = f.product_key
JOIN star.dim_store   s ON s.store_key   = f.store_key
WHERE d.year = 2025 AND d.quarter = 2
GROUP BY p.category_name, s.region_name
$q$),
('snowflake', $q$
SELECT cat.category_name, r.region_name, sum(f.amount) AS revenue, sum(f.quantity) AS units
FROM snowflake.fact_sales f
JOIN snowflake.dim_date        d   ON d.date_key         = f.date_key
JOIN snowflake.dim_product     p   ON p.product_key      = f.product_key
JOIN snowflake.dim_subcategory sc  ON sc.subcategory_key = p.subcategory_key
JOIN snowflake.dim_category    cat ON cat.category_key   = sc.category_key
JOIN snowflake.dim_store       s   ON s.store_key        = f.store_key
JOIN snowflake.dim_city        ci  ON ci.city_key        = s.city_key
JOIN snowflake.dim_region      r   ON r.region_key       = ci.region_key
WHERE d.year = 2025 AND d.quarter = 2
GROUP BY cat.category_name, r.region_name
$q$),
-- тот же запрос снежинки, но измерение даты с фильтром стоит в тексте последним
('snowflake_date_last', $q$
SELECT cat.category_name, r.region_name, sum(f.amount) AS revenue, sum(f.quantity) AS units
FROM snowflake.fact_sales f
JOIN snowflake.dim_product     p   ON p.product_key      = f.product_key
JOIN snowflake.dim_subcategory sc  ON sc.subcategory_key = p.subcategory_key
JOIN snowflake.dim_category    cat ON cat.category_key   = sc.category_key
JOIN snowflake.dim_store       s   ON s.store_key        = f.store_key
JOIN snowflake.dim_city        ci  ON ci.city_key        = s.city_key
JOIN snowflake.dim_region      r   ON r.region_key       = ci.region_key
JOIN snowflake.dim_date        d   ON d.date_key         = f.date_key
WHERE d.year = 2025 AND d.quarter = 2
GROUP BY cat.category_name, r.region_name
$q$);

-- Отпечаток результата: все строки, отсортированные как текст, в один md5
CREATE FUNCTION pg_temp.result_md5(q text) RETURNS TABLE (rows bigint, total_revenue numeric, md5 text)
LANGUAGE plpgsql AS $f$
BEGIN
  RETURN QUERY EXECUTE format(
    'SELECT count(*), sum(revenue), md5(string_agg(t::text, %L ORDER BY t::text)) FROM (%s) t', '|', q);
END $f$;

-- Замер: прогрев, затем N прогонов EXPLAIN ANALYZE; медианы времени и разбор узлов последнего плана
CREATE FUNCTION pg_temp.plan_stats(q text, runs int DEFAULT 5)
RETURNS TABLE (tables int, join_nodes int, planning_ms numeric, execution_ms numeric,
               min_ms numeric, max_ms numeric, shared_hit bigint, shared_read bigint)
LANGUAGE plpgsql AS $f$
DECLARE
  p json;
  pt numeric[] := '{}';
  et numeric[] := '{}';
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || q INTO p;
  FOR i IN 1..runs LOOP
    EXECUTE 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' || q INTO p;
    pt := pt || (p->0->>'Planning Time')::numeric;
    et := et || (p->0->>'Execution Time')::numeric;
  END LOOP;
  RETURN QUERY
  WITH RECURSIVE nodes(n) AS (
    SELECT p->0->'Plan'
    UNION ALL
    SELECT c FROM nodes, json_array_elements(nodes.n->'Plans') AS c
  )
  SELECT (SELECT count(DISTINCT n->>'Relation Name') FROM nodes)::int,
         (SELECT count(*) FROM nodes WHERE n->>'Node Type' IN ('Hash Join', 'Merge Join', 'Nested Loop'))::int,
         (SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY x)::numeric, 3) FROM unnest(pt) x),
         (SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY x)::numeric, 1) FROM unnest(et) x),
         (SELECT round(min(x), 1) FROM unnest(et) x),
         (SELECT round(max(x), 1) FROM unnest(et) x),
         (p->0->'Plan'->>'Shared Hit Blocks')::bigint,
         (p->0->'Plan'->>'Shared Read Blocks')::bigint;
END $f$;

\echo '--- Пределы планировщика, в пределах которых он переставляет JOIN'
SELECT name, setting FROM pg_settings
WHERE name IN ('join_collapse_limit', 'from_collapse_limit', 'geqo_threshold', 'geqo',
               'max_parallel_workers_per_gather', 'shared_buffers')
ORDER BY name;

\echo '--- Пять верхних строк результата на звезде'
SELECT format('SELECT * FROM (%s) t ORDER BY revenue DESC LIMIT 5', sql) FROM demo_queries WHERE name = 'star' \gexec

\echo '--- Результаты двух схем совпадают? (строк, сумма выручки, md5 всех строк)'
SELECT q.name AS "запрос", r.* FROM demo_queries q, pg_temp.result_md5(q.sql) r ORDER BY q.name DESC;

\echo '--- План на звезде'
SELECT 'EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) ' || sql FROM demo_queries WHERE name = 'star' \gexec

\echo '--- План на снежинке'
SELECT 'EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) ' || sql FROM demo_queries WHERE name = 'snowflake' \gexec

\echo '--- Замер: таблиц в плане, узлов JOIN, медианы планирования и выполнения по 5 прогонам'
SELECT q.name AS "схема", s.* FROM demo_queries q, pg_temp.plan_stats(q.sql) s
WHERE q.name IN ('star', 'snowflake') ORDER BY q.name DESC;

\echo '--- Дата последней в тексте, join_collapse_limit = 8: планировщик сам ставит фильтр по дате первым'
SELECT 'EXPLAIN (COSTS OFF) ' || sql FROM demo_queries WHERE name = 'snowflake_date_last' \gexec

\echo '--- То же при join_collapse_limit = 1: JOIN идут ровно в порядке текста запроса'
SET join_collapse_limit = 1;
SELECT 'EXPLAIN (COSTS OFF) ' || sql FROM demo_queries WHERE name = 'snowflake_date_last' \gexec
RESET join_collapse_limit;

\echo '--- Замер обоих вариантов, по 5 прогонов'
SELECT 'join_collapse_limit = 8' AS "вариант", s.* FROM demo_queries q, pg_temp.plan_stats(q.sql) s
WHERE q.name = 'snowflake_date_last';
SET join_collapse_limit = 1;
SELECT 'join_collapse_limit = 1' AS "вариант", s.* FROM demo_queries q, pg_temp.plan_stats(q.sql) s
WHERE q.name = 'snowflake_date_last';
RESET join_collapse_limit;

\echo '--- Удаление лишнего JOIN: LEFT JOIN к измерению без его колонок в запросе'
EXPLAIN (COSTS OFF)
SELECT sum(f.amount) FROM star.fact_sales f
LEFT JOIN star.dim_customer c ON c.customer_key = f.customer_key;

\echo '--- То же через INNER JOIN: внешний ключ есть, но JOIN остаётся'
EXPLAIN (COSTS OFF)
SELECT sum(f.amount) FROM star.fact_sales f
JOIN star.dim_customer c ON c.customer_key = f.customer_key;
