-- pgvector 0.8.6, PostgreSQL 18.4, прогнано на стенде 2026-08-30
-- Шаг 2: построение индекса HNSW для операции cosine distance.
--
-- vector_cosine_ops — класс операторов под оператор расстояния <=> (косинусное
-- расстояние). Параметры m и ef_construction явно повторяют значения по умолчанию
-- документации pgvector (m=16, ef_construction=64): в отличие от IVFFlat, HNSW не
-- требует отдельной фазы обучения и строится сразу на заполненной таблице.
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Проверка, что индекс создан и планировщик о нём знает.
\d documents
