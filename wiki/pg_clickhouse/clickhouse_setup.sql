-- ClickHouse 25.8.33.6, синтаксис по официальной документации ClickHouse, прогнано на стенде 2026-09-03
-- Создаёт демо-таблицу событий и наполняет её синтетическими данными,
-- через которую дальше проверяется pushdown из PostgreSQL.

CREATE DATABASE IF NOT EXISTS analytics;

CREATE TABLE analytics.events
(
    event_id UInt64,
    user_id UInt32,
    event_type String,
    amount Decimal(10, 2),
    created_at DateTime,
    raw_uint64 UInt64
)
ENGINE = MergeTree
ORDER BY (created_at, event_id);

INSERT INTO analytics.events
SELECT
    number AS event_id,
    toUInt32(1 + rand() % 5000) AS user_id,
    ['view', 'click', 'purchase'][1 + rand() % 3] AS event_type,
    round((rand() % 10000) / 100.0, 2) AS amount,
    toDateTime('2026-08-01 00:00:00') + toIntervalSecond(rand() % (30 * 24 * 3600)) AS created_at,
    -- у первой строки намеренно максимальное значение UInt64, чтобы показать
    -- переполнение bigint в PostgreSQL при чтении через foreign table
    if(number = 0, 18446744073709551615, number) AS raw_uint64
FROM numbers(1000000);

-- Представление с безопасным для PostgreSQL текстовым представлением raw_uint64.
-- Обходной путь из документации pg_clickhouse: toString() на стороне ClickHouse.
CREATE VIEW analytics.events_uint64_safe AS
SELECT
    event_id,
    toString(raw_uint64) AS raw_uint64_str
FROM analytics.events;

SELECT count() AS rows_loaded FROM analytics.events;
