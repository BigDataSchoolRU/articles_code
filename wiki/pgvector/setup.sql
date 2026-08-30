-- pgvector 0.8.6 (Homebrew, бутылка arm64), PostgreSQL 18.4, прогнано на стенде 2026-08-30
-- Шаг 1: расширение, таблица с векторной колонкой, тестовые данные.
--
-- Расширение регистрируется один раз на базу данных. База pgvector_demo создаётся
-- отдельно (см. RUNBOOK) командой createdb, потому что CREATE DATABASE в PostgreSQL
-- не принимает IF NOT EXISTS — этот файл уже подключается к готовой базе.
CREATE EXTENSION IF NOT EXISTS vector;

-- Вспомогательная функция для демо-данных. Собирает вектор нужной размерности из
-- случайных чисел в диапазоне [-1, 1]. VOLATILE обязателен: без него планировщик
-- Postgres вправе вычислить не-коррелированное значение один раз на весь запрос
-- и подставить его во все строки — реальные грабли, пойманные при подготовке
-- этого демо (см. RUNBOOK, раздел «если не так»).
CREATE OR REPLACE FUNCTION random_vector(dim int) RETURNS vector AS $$
DECLARE
    arr real[] := '{}';
BEGIN
    FOR i IN 1..dim LOOP
        arr := arr || (random() * 2 - 1)::real;
    END LOOP;
    RETURN arr::vector;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- Таблица документов: обычная бизнес-колонка category рядом с vector-колонкой —
-- в этом и состоит архитектурная идея pgvector, вектор живёт в той же строке,
-- что и остальные данные, без выноса в отдельное хранилище.
DROP TABLE IF EXISTS documents;
CREATE TABLE documents (
    id bigserial PRIMARY KEY,
    category text NOT NULL,
    embedding vector(128) NOT NULL
);

-- 5000 строк, из них 5% (250 строк) в редкой категории 'niche'. Размерность 128
-- и объём выбраны так, чтобы дальше на шаге с фильтром WHERE было видно эффект
-- overfiltering — с более крупным индексом реального RAG-корпуса тот же эффект
-- проявляется на любой достаточно избирательной категории.
INSERT INTO documents (category, embedding)
SELECT
    CASE WHEN i % 20 = 0 THEN 'niche' ELSE 'popular' END,
    random_vector(128)
FROM generate_series(1, 5000) AS i;

-- Проверка: строки разные (без этой проверки описанный выше баг с
-- не-коррелированным подзапросом было бы не видно на глаз).
SELECT category, count(*) FROM documents GROUP BY category;
SELECT count(DISTINCT embedding) AS distinct_vectors FROM documents;
