-- pg_clickhouse v0.3.x (ghcr.io/clickhouse/pg_clickhouse:18, PostgreSQL 18.4),
-- синтаксис по официальной документации ClickHouse/pg_clickhouse, прогнано на стенде 2026-09-03
-- Подключает ClickHouse как foreign server и импортирует схему analytics
-- целиком через IMPORT FOREIGN SCHEMA.

CREATE EXTENSION pg_clickhouse;

-- driver 'binary' — нативный протокол ClickHouse, порт по умолчанию для него
-- на обычном (не Cloud) хосте 9004, но сервер в docker-compose слушает
-- порт 9000 (стандартный порт native-протокола самого ClickHouse), поэтому
-- порт указан явно.
CREATE SERVER analytics_srv FOREIGN DATA WRAPPER clickhouse_fdw
    OPTIONS (driver 'binary', host 'clickhouse', port '9000', dbname 'analytics');

CREATE USER MAPPING FOR CURRENT_USER SERVER analytics_srv
    OPTIONS (user 'default', password 'demo_pass');

CREATE SCHEMA analytics;
IMPORT FOREIGN SCHEMA analytics FROM SERVER analytics_srv INTO analytics;

-- Проверка: список импортированных foreign-таблиц и типы колонок events.
\det+ analytics.*
\d analytics.events
