-- Nexus SQL, PGWire-интерфейс peerdb-server v0.37.5, порт 9900, прогнано на стенде 2026-09-03.
-- Подключение: postgresql://postgres:peerdb@localhost:9900/postgres
--
-- Это не обычный Postgres: Nexus сам парсит расширения CREATE PEER / CREATE MIRROR и
-- транслирует их в вызовы Flow API, который заводит workflow в Temporal.

-- Источник — база "source" внутри того же catalog-Postgres (см. source_schema.sql)
CREATE PEER pg_source FROM POSTGRES WITH (
    host = 'catalog',
    port = '5432',
    user = 'postgres',
    password = 'postgres',
    database = 'source'
);

-- Назначение — отдельный ClickHouse из clickhouse_target_compose.yml
CREATE PEER ch_target FROM CLICKHOUSE WITH (
    host = 'clickhouse-target',
    port = '9000',
    user = 'peerdb',
    password = 'peerdb_demo_pass',
    database = 'peerdb_target',
    disable_tls = 'true'
);

-- do_initial_copy=true снимает полный снапшот таблицы orders, дальше mirror сам
-- переключается на потоковое CDC через слот логической репликации Postgres (плагин pgoutput)
CREATE MIRROR orders_cdc FROM pg_source TO ch_target
WITH TABLE MAPPING (public.orders:peerdb_target.orders_cdc)
WITH (
    do_initial_copy = true
);
