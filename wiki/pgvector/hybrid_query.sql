-- pgvector 0.8.6, PostgreSQL 18.4, прогнано на стенде 2026-08-30
-- Шаг 4: гибридный запрос — ANN-поиск плюс фильтр WHERE по обычной колонке,
-- и демонстрация overfiltering (с версии pgvector 0.8.0).
--
-- Overfiltering: приближённый индекс сканирует граф по близости вектора, а
-- WHERE-фильтр применяется уже ПОСЛЕ того, как кандидаты найдены. Если
-- искомая категория редкая, среди найденных кандидатов её может не хватить
-- до LIMIT — запрос вернёт меньше строк, чем просили, хотя подходящие строки
-- в таблице есть.
CREATE TEMP TABLE q_anchor AS SELECT random_vector(128) AS v;

-- На таблице в 5000 строк планировщик Postgres по стоимости сам выбирает
-- Seq Scan для запроса с фильтром по редкой категории (собственная оценка
-- планировщика для этого узла плана — 25 строк, при реальных 250 строках
-- категории niche; такую оценку дешевле отсортировать перебором, чем идти
-- в HNSW-индекс) — тогда поиск точный и overfiltering не проявляется в
-- принципе. enable_seqscan=off здесь
-- используется только для демонстрации: он форсирует именно ANN-путь через
-- индекс. На таблице промышленного размера (миллионы строк) планировщик
-- выбирает индекс сам, без этой команды.
SET enable_seqscan = off;

SET hnsw.iterative_scan = off;
EXPLAIN SELECT id FROM documents
    WHERE category = 'niche'
    ORDER BY embedding <=> (SELECT v FROM q_anchor)
    LIMIT 20;

SELECT 'iterative_scan = off' AS mode, count(*) AS rows_returned
FROM (
    SELECT id FROM documents
    WHERE category = 'niche'
    ORDER BY embedding <=> (SELECT v FROM q_anchor)
    LIMIT 20
) t;

-- relaxed_order снимает overfiltering: движок продолжает расширять скан графа,
-- пока не наберёт LIMIT строк или не упрётся в hnsw.max_scan_tuples (20000 по
-- умолчанию), ценой точного порядка результата по расстоянию.
SET hnsw.iterative_scan = relaxed_order;

SELECT 'iterative_scan = relaxed_order' AS mode, count(*) AS rows_returned
FROM (
    SELECT id FROM documents
    WHERE category = 'niche'
    ORDER BY embedding <=> (SELECT v FROM q_anchor)
    LIMIT 20
) t;

RESET enable_seqscan;
RESET hnsw.iterative_scan;
