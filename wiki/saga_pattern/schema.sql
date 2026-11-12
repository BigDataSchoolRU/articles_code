-- postgres 18.6, прогнано на стенде 2026-11-12
-- Четыре базы в одном сервере: у каждого сервиса своя (database per service), общей транзакции
-- между базами в PostgreSQL нет, это и есть задача, которую решает сага.
CREATE DATABASE orders;
CREATE DATABASE inventory;
CREATE DATABASE payments;
CREATE DATABASE saga;

-- Сервис заказов
\connect orders
CREATE TABLE orders (
    order_id   text PRIMARY KEY,
    customer   text NOT NULL,
    sku        text NOT NULL,
    qty        int  NOT NULL CHECK (qty > 0),
    amount     numeric(12, 2) NOT NULL,
    status     text NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'CANCELLED')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Сервис склада. Резерв в статусе PENDING это semantic lock: товар занят сагой, которая ещё не закончилась
\connect inventory
CREATE TABLE stock (
    sku       text PRIMARY KEY,
    available int  NOT NULL CHECK (available >= 0)
);
CREATE TABLE reservations (
    idem_key   text PRIMARY KEY,          -- ключ идемпотентности шага саги
    saga_id    text NOT NULL,
    sku        text NOT NULL REFERENCES stock,
    qty        int  NOT NULL,
    status     text NOT NULL CHECK (status IN ('PENDING', 'COMMITTED', 'RELEASED')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Сервис оплаты
\connect payments
CREATE TABLE accounts (
    customer text PRIMARY KEY,
    balance  numeric(12, 2) NOT NULL CHECK (balance >= 0)
);
CREATE TABLE payments (
    idem_key   text PRIMARY KEY,
    saga_id    text NOT NULL,
    customer   text NOT NULL REFERENCES accounts,
    amount     numeric(12, 2) NOT NULL,
    status     text NOT NULL CHECK (status IN ('CHARGED', 'REFUNDED')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Журнал оркестратора: состояние каждой саги и пройденные шаги
\connect saga
CREATE TABLE saga_instances (
    saga_id    text PRIMARY KEY,
    payload    jsonb NOT NULL,
    state      text NOT NULL CHECK (state IN ('RUNNING', 'COMPENSATING', 'COMPLETED', 'COMPENSATED')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE saga_log (
    id      bigserial PRIMARY KEY,
    saga_id text NOT NULL REFERENCES saga_instances,
    step    text NOT NULL,
    action  text NOT NULL CHECK (action IN ('DO', 'COMPENSATE')),
    status  text NOT NULL CHECK (status IN ('DONE', 'FAILED')),
    detail  text,
    at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
