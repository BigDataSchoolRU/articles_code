-- postgres 18.6, прогнано на стенде 2026-11-05: витрина и таблица состояния синхронизаций

-- Витрина, которую собрал аналитик (в жизни это модель dbt): по строке на клиента
CREATE SCHEMA analytics;
CREATE TABLE analytics.customer_scores (
    customer_id integer PRIMARY KEY,
    email       text          NOT NULL,
    plan        text          NOT NULL,
    ltv         numeric(10,2) NOT NULL,
    churn_risk  text          NOT NULL
);

-- 25 детерминированных клиентов, чтобы прогон повторялся строка в строку
INSERT INTO analytics.customer_scores
SELECT i,
       'client' || i || '@example.com',
       (ARRAY['free', 'pro', 'team'])[i % 3 + 1],
       (i * 137 % 5000) + 0.50,
       CASE WHEN i % 5 = 0 THEN 'high' WHEN i % 2 = 0 THEN 'medium' ELSE 'low' END
FROM generate_series(1, 25) AS i;

-- Состояние движка Reverse ETL: снимок прошлого успешного прогона.
-- По каждой синхронизации хранится первичный ключ и хэш строки, а не сами данные.
CREATE SCHEMA reverse_etl;
CREATE TABLE reverse_etl.sync_snapshot (
    sync_name text        NOT NULL,
    pk        text        NOT NULL,
    row_hash  text        NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sync_name, pk)
);
