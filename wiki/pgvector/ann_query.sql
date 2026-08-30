-- pgvector 0.8.6, PostgreSQL 18.4, прогнано на стенде 2026-08-30
-- Шаг 3: обычный ANN-запрос без фильтра, оператор косинусного расстояния <=>.
--
-- Вектор запроса берётся тем же генератором, что и данные в demo, — это
-- "запрос", для которого ищем ближайшие соседи. В реальном RAG-сценарии на этом
-- месте стоял бы эмбеддинг вопроса пользователя.
CREATE TEMP TABLE q_anchor AS SELECT random_vector(128) AS v;

-- hnsw.ef_search управляет шириной поиска по графу на этапе запроса (по
-- умолчанию 40). Явно не меняем — демонстрируем поведение по умолчанию.
EXPLAIN SELECT id, category
FROM documents
ORDER BY embedding <=> (SELECT v FROM q_anchor)
LIMIT 5;

SELECT id, category, round((embedding <=> (SELECT v FROM q_anchor))::numeric, 4) AS distance
FROM documents
ORDER BY embedding <=> (SELECT v FROM q_anchor)
LIMIT 5;
