-- postgres 18.6 в Docker, pageinspect из contrib, прогнано на стенде 2026-11-06
-- HOT-обновление: новая версия на той же странице, индекс не трогается.
CREATE EXTENSION IF NOT EXISTS pageinspect;
DROP TABLE IF EXISTS hot_demo, ff100, ff90 CASCADE;

\echo '--- 3.1 цепочка HOT на одной странице'
CREATE TABLE hot_demo (
    id  int PRIMARY KEY,
    sku text NOT NULL,
    qty int NOT NULL
) WITH (autovacuum_enabled = off);
CREATE INDEX hot_demo_sku ON hot_demo (sku);
INSERT INTO hot_demo VALUES (1, 'A-1', 10), (2, 'B-2', 20);
-- qty не входит ни в один индекс: три обновления подряд, каждое отдельной транзакцией
UPDATE hot_demo SET qty = 11 WHERE id = 1;
UPDATE hot_demo SET qty = 12 WHERE id = 1;
UPDATE hot_demo SET qty = 13 WHERE id = 1;
-- sku проиндексирована: такое обновление HOT быть не может
UPDATE hot_demo SET sku = 'B-2x' WHERE id = 2;
SELECT ctid, * FROM hot_demo ORDER BY id;

\set page_items 'SELECT lp, lp_flags, t_xmin, t_xmax, t_ctid, f.raw_flags FROM heap_page_items(get_raw_page(''hot_demo'', 0)) h, LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) f ORDER BY lp'
:page_items;
-- первичный ключ: запись на строку id=1 одна и указывает на начало цепочки,
-- на строку id=2 две, потому что обновлённая версия получила свою запись в каждом индексе
SELECT itemoffset, ctid, data FROM bt_page_items('hot_demo_pkey', 1);

\echo '--- 3.2 после VACUUM: начало цепочки становится перенаправлением (lp_flags 2) на живую версию'
VACUUM hot_demo;
:page_items;

\echo '--- 3.3 fillfactor: HOT нужно свободное место на той же странице'
-- одинаковые таблицы, разница только в fillfactor
CREATE TABLE ff100 (id int PRIMARY KEY, qty int NOT NULL, pad text NOT NULL)
    WITH (autovacuum_enabled = off, fillfactor = 100);
CREATE TABLE ff90  (id int PRIMARY KEY, qty int NOT NULL, pad text NOT NULL)
    WITH (autovacuum_enabled = off, fillfactor = 90);
INSERT INTO ff100 SELECT g, 0, repeat('x', 60) FROM generate_series(1, 2000) g;
INSERT INTO ff90  SELECT g, 0, repeat('x', 60) FROM generate_series(1, 2000) g;
SELECT 'ff100' AS tbl, pg_relation_size('ff100') / 8192 AS pages,
       (SELECT upper - lower FROM page_header(get_raw_page('ff100', 0))) AS page0_free_bytes
UNION ALL
SELECT 'ff90', pg_relation_size('ff90') / 8192,
       (SELECT upper - lower FROM page_header(get_raw_page('ff90', 0)));
-- пять строк с первой страницы, неиндексированная колонка
UPDATE ff100 SET qty = qty + 1 WHERE id <= 5;
UPDATE ff90  SET qty = qty + 1 WHERE id <= 5;
SELECT 'ff100' AS tbl, array_agg(ctid ORDER BY id) AS new_ctids FROM ff100 WHERE id <= 5
UNION ALL
SELECT 'ff90', array_agg(ctid ORDER BY id) FROM ff90 WHERE id <= 5;

\echo '--- 3.4 счётчики обновлений в pg_stat_user_tables'
-- статистика сессии уходит в общую память, когда сессия простаивает: просим сделать это сразу
SELECT pg_stat_force_next_flush();
SELECT relname, n_tup_upd, n_tup_hot_upd, n_tup_newpage_upd
FROM pg_stat_user_tables WHERE relname IN ('hot_demo', 'ff100', 'ff90') ORDER BY relname;
