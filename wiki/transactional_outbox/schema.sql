-- PostgreSQL 18.6, прогнано на стенде 2026-11-06: сервис заказов с таблицей outbox и сервис лояльности с inbox

-- Бизнес-таблица сервиса заказов
CREATE TABLE orders (
    id         bigserial PRIMARY KEY,
    customer   text          NOT NULL,
    amount     numeric(10,2) NOT NULL CHECK (amount > 0),
    status     text          NOT NULL DEFAULT 'created',
    created_at timestamptz   NOT NULL DEFAULT now()
);

-- Outbox: колонки id, aggregatetype, aggregateid, type, payload это имена по умолчанию
-- у Debezium Outbox Event Router. published_at нужна только ретранслятору-опросчику.
CREATE TABLE outbox (
    id            uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregatetype varchar(255) NOT NULL,
    aggregateid   varchar(255) NOT NULL,
    type          varchar(255) NOT NULL,
    payload       jsonb        NOT NULL,
    created_at    timestamptz  NOT NULL DEFAULT clock_timestamp(),
    published_at  timestamptz
);

-- Частичный индекс: опросчик читает только неотправленное, отправленные строки индекс не раздувают
CREATE INDEX outbox_unpublished ON outbox (created_at) WHERE published_at IS NULL;

-- Сервис лояльности в своей схеме (в жизни это отдельная база): начисленные баллы и inbox
CREATE SCHEMA loyalty;

CREATE TABLE loyalty.points (
    customer text    PRIMARY KEY,
    points   integer NOT NULL DEFAULT 0
);

-- Inbox: id уже обработанных событий. Вставка в inbox и эффект идут одной транзакцией
CREATE TABLE loyalty.inbox (
    event_id     uuid        PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);
