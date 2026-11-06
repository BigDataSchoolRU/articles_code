-- postgres 18.6, прогнано на стенде 2026-11-06: схема хранилища событий на одной таблице

-- Журнал событий. Единственный источник истины, строки только добавляются.
CREATE TABLE events (
    -- глобальная позиция: сквозной номер события во всём журнале, по ней читают проекторы
    global_position bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- поток = один агрегат (здесь один заказ), версия = номер события внутри потока
    stream_id       text        NOT NULL,
    stream_version  integer     NOT NULL CHECK (stream_version > 0),
    event_type      text        NOT NULL,
    -- версия схемы payload: старые события не переписываются, их поднимает апкастер при чтении
    schema_version  integer     NOT NULL DEFAULT 1,
    payload         jsonb       NOT NULL,
    metadata        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    -- идентификатор транзакции записи: нужен проектору, чтобы не пропускать поздно зафиксированные события
    transaction_id  xid8        NOT NULL DEFAULT pg_current_xact_id(),
    recorded_at     timestamptz NOT NULL DEFAULT clock_timestamp(),
    -- оптимистичная конкурентность: две записи с одной версией в одном потоке невозможны
    CONSTRAINT events_stream_version_uq UNIQUE (stream_id, stream_version)
);

CREATE INDEX events_tx_position_idx ON events (transaction_id, global_position);

-- Журнал неизменяем: UPDATE, DELETE и TRUNCATE отклоняются триггером.
CREATE FUNCTION events_forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'журнал событий только на добавление: % запрещён', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION events_forbid_change();

CREATE TRIGGER events_no_truncate
    BEFORE TRUNCATE ON events
    FOR EACH STATEMENT EXECUTE FUNCTION events_forbid_change();

-- Снапшот: кэш состояния агрегата на версии N. Его можно стереть и построить заново из журнала.
CREATE TABLE snapshots (
    stream_id      text        PRIMARY KEY,
    stream_version integer     NOT NULL,
    state          jsonb       NOT NULL,
    taken_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Чекпойнт проектора: до какого места журнала он дочитал.
CREATE TABLE projection_checkpoints (
    projection      text   PRIMARY KEY,
    last_tx         xid8   NOT NULL DEFAULT '0',
    last_position   bigint NOT NULL DEFAULT 0
);

-- Модель чтения: сводка по заказу для экрана «Мои заказы». Производная от журнала.
CREATE TABLE order_summary (
    order_id    text    PRIMARY KEY,
    customer    text    NOT NULL,
    status      text    NOT NULL,
    lines       jsonb   NOT NULL DEFAULT '{}'::jsonb,
    items_count integer NOT NULL DEFAULT 0,
    total       numeric(12, 2) NOT NULL DEFAULT 0,
    -- версия потока, до которой модель уже обновлена: защита от повторной доставки
    version     integer NOT NULL
);
