-- PostgreSQL 18.6, прогнано на стенде 2026-11-13: источник событий метаданных на event trigger и pg_notify
-- Выполняется один раз при первом старте контейнера на чистом томе (docker-entrypoint-initdb.d).

-- Данные демо: сырой слой и два слоя производных представлений
CREATE SCHEMA raw;
CREATE SCHEMA mart;
CREATE SCHEMA report;

CREATE TABLE raw.customers (
    id   int PRIMARY KEY,
    name text NOT NULL,
    city text
);

-- Роль аналитика: читает всё, что появляется в mart и report (права по умолчанию)
CREATE ROLE analyst NOLOGIN;
GRANT USAGE ON SCHEMA mart, report TO analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA mart, report GRANT SELECT ON TABLES TO analyst;

-- Служебная схема meta: это и есть граф метаданных, который обновляют события
CREATE SCHEMA meta;

-- Журнал событий. pg_notify несёт только id строки: payload ограничен 8000 байт,
-- а строка в таблице переживает отсутствие слушателя
CREATE TABLE meta.events (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    txid    xid8        NOT NULL DEFAULT pg_current_xact_id(),
    event   text        NOT NULL,           -- ddl_command_end или sql_drop
    tag     text        NOT NULL,           -- ALTER TABLE, CREATE VIEW, REVOKE ...
    app     text        NOT NULL,           -- application_name сессии, которая сделала изменение
    objects jsonb       NOT NULL,           -- затронутые объекты
    query   text                            -- текст команды, обрезанный
);

-- Колонки, которые каталог знает на текущий момент
CREATE TABLE meta.columns (
    relation    text NOT NULL,
    column_name text NOT NULL,
    PRIMARY KEY (relation, column_name)
);

-- Lineage: колонка-источник -> представление, представление -> внешний потребитель
CREATE TABLE meta.lineage (
    upstream   text NOT NULL,
    downstream text NOT NULL,
    kind       text NOT NULL,               -- view или consumer
    PRIMARY KEY (upstream, downstream)
);

-- Внешние потребители регистрируются в каталоге руками: базе про дашборды ничего не известно
INSERT INTO meta.lineage VALUES
    ('mart.customers_by_city', 'bi.city_dashboard', 'consumer'),
    ('report.newsletter',      'crm.mailing_job',   'consumer');

CREATE TABLE meta.tags (
    asset  text NOT NULL,
    tag    text NOT NULL,
    source text NOT NULL,                   -- какое правило или какой предок поставил тег
    at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (asset, tag)
);

CREATE TABLE meta.actions (
    id     bigserial PRIMARY KEY,
    at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    event  bigint,                          -- id события, на которое среагировало правило
    rule   text NOT NULL,
    asset  text NOT NULL,
    action text NOT NULL
);

-- Какие колонки читает представление: по зависимостям его правила перезаписи в pg_depend
CREATE FUNCTION meta.view_reads(v oid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT coalesce(jsonb_agg(DISTINCT n.nspname || '.' || c.relname || '.' || a.attname), '[]'::jsonb)
    FROM pg_rewrite rw
    JOIN pg_depend d     ON d.classid = 'pg_rewrite'::regclass AND d.objid = rw.oid
                        AND d.refclassid = 'pg_class'::regclass AND d.refobjsubid > 0
    JOIN pg_class c      ON c.oid = d.refobjid
    JOIN pg_namespace n  ON n.oid = c.relnamespace
    JOIN pg_attribute a  ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
    WHERE rw.ev_class = v AND d.refobjid <> v
$$;

-- Конец любой DDL-команды: собрать затронутые объекты, записать событие, отправить его id
CREATE FUNCTION meta.on_ddl_end() RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE
    r    record;
    objs jsonb := '[]'::jsonb;
    eid  bigint;
BEGIN
    FOR r IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
        -- изменения самой схемы meta событиями не считаем
        IF r.schema_name = 'meta' OR r.in_extension THEN
            CONTINUE;
        END IF;
        objs := objs || jsonb_build_object(
            'type',     r.object_type,
            'identity', r.object_identity,
            -- состав колонок на момент события, чтобы слушатель мог сравнить с тем, что знал раньше
            'columns',  CASE WHEN r.object_type IN ('table', 'view') THEN
                            (SELECT jsonb_agg(attname::text ORDER BY attnum)
                             FROM pg_attribute
                             WHERE attrelid = r.objid AND attnum > 0 AND NOT attisdropped)
                        END,
            'reads',    CASE WHEN r.object_type = 'view' THEN meta.view_reads(r.objid) END);
    END LOOP;
    IF jsonb_array_length(objs) = 0 THEN
        RETURN;
    END IF;
    INSERT INTO meta.events (event, tag, app, objects, query)
    VALUES (tg_event, tg_tag, current_setting('application_name'), objs, left(current_query(), 300))
    RETURNING id INTO eid;
    -- уведомление уйдёт слушателям только после коммита транзакции с DDL
    PERFORM pg_notify('meta_events', eid::text);
END
$$;

-- Удаление объектов: колонки, таблицы, представления, в том числе снесённые каскадом
CREATE FUNCTION meta.on_sql_drop() RETURNS event_trigger
LANGUAGE plpgsql AS $$
DECLARE
    r    record;
    objs jsonb := '[]'::jsonb;
    eid  bigint;
BEGIN
    FOR r IN SELECT * FROM pg_event_trigger_dropped_objects() LOOP
        IF r.schema_name = 'meta'
           OR r.object_type NOT IN ('table', 'view', 'materialized view', 'table column') THEN
            CONTINUE;
        END IF;
        objs := objs || jsonb_build_object(
            'type',     r.object_type,
            'identity', r.object_identity,
            'original', r.original);         -- false: объект снесён каскадом, а не назван в команде
    END LOOP;
    IF jsonb_array_length(objs) = 0 THEN
        RETURN;
    END IF;
    INSERT INTO meta.events (event, tag, app, objects, query)
    VALUES (tg_event, tg_tag, current_setting('application_name'), objs, left(current_query(), 300))
    RETURNING id INTO eid;
    PERFORM pg_notify('meta_events', eid::text);
END
$$;

CREATE EVENT TRIGGER meta_ddl_end ON ddl_command_end EXECUTE FUNCTION meta.on_ddl_end();
CREATE EVENT TRIGGER meta_sql_drop ON sql_drop EXECUTE FUNCTION meta.on_sql_drop();
