-- pg_clickhouse v0.3.x (ghcr.io/clickhouse/pg_clickhouse:18, PostgreSQL 18.4),
-- ClickHouse 25.8.33.6, прогнано на стенде 2026-09-03
-- Три проверенных на реальном стенде случая: успешный pushdown, локальный
-- JOIN между local- и remote-таблицами (не проталкивается), переполнение
-- UInt64 при чтении через foreign table.

\timing on

-- ── 1. Успешный pushdown: WHERE + GROUP BY + count() ──────────────────────
-- В "Remote SQL" виден запрос, целиком отправленный в ClickHouse: PostgreSQL
-- получает уже посчитанный результат, а не сырые строки.
EXPLAIN (VERBOSE)
SELECT event_type, count(*) AS cnt
FROM analytics.events
WHERE created_at >= '2026-08-15'
GROUP BY event_type;

SELECT event_type, count(*) AS cnt
FROM analytics.events
WHERE created_at >= '2026-08-15'
GROUP BY event_type
ORDER BY event_type;

-- ── 2. JOIN между локальной таблицей PostgreSQL и foreign table ClickHouse ─
-- Документация предупреждает, что такой JOIN неэффективен. На практике это
-- значит: pg_clickhouse проталкивает не JOIN, а голый SELECT одной колонки
-- без фильтра ("Remote SQL: SELECT user_id FROM analytics.events" — читает
-- всю таблицу), а сам JOIN и агрегацию после него PostgreSQL делает уже
-- локально (Hash Join, HashAggregate в плане).
CREATE TABLE local_users (user_id bigint PRIMARY KEY, segment text);
INSERT INTO local_users
SELECT g, CASE WHEN g % 2 = 0 THEN 'even' ELSE 'odd' END
FROM generate_series(1, 5000) g;

EXPLAIN (VERBOSE)
SELECT lu.segment, count(*) AS cnt
FROM analytics.events e
JOIN local_users lu ON lu.user_id = e.user_id
GROUP BY lu.segment;

-- ── 3. Переполнение UInt64 и обходной путь toString() ──────────────────────
-- Значение 18446744073709551615 (2^64-1) больше максимума bigint —
-- foreign table читает колонку raw_uint64 как bigint и падает с ошибкой.
SELECT raw_uint64
FROM analytics.events
WHERE event_id = 0;

-- Обходной путь из документации: на стороне ClickHouse обернуть колонку в
-- toString() (см. VIEW analytics.events_uint64_safe в clickhouse_setup.sql)
-- и читать её как text через отдельную foreign table.
SELECT raw_uint64_str
FROM analytics.events_uint64_safe
WHERE event_id = 0;
