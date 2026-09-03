-- PostgreSQL 18-alpine внутри контейнера catalog self-hosted стенда PeerDB v0.37.5,
-- прогнано на стенде 2026-09-03. Подключение: postgresql://postgres:postgres@localhost:9901/postgres
--
-- Создаёт отдельную демо-базу "source" с таблицей orders для CDC в ClickHouse через PeerDB.
-- Отдельная база нужна, чтобы не путать демо-данные с каталогом метаданных самого PeerDB —
-- он тоже живёт в этом Postgres, в базе postgres.

DROP DATABASE IF EXISTS source;
CREATE DATABASE source;

\c source

CREATE TABLE orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer TEXT NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 20 стартовых строк — их заберёт начальный снапшот при создании mirror
INSERT INTO orders (customer, amount, status)
SELECT 'customer_' || g, (g * 1.5)::numeric(10, 2), 'new'
FROM generate_series(1, 20) AS g;
