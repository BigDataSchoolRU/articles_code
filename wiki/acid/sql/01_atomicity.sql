-- postgres 18.6 в Docker, прогнано на стенде 2026-11-05
-- Atomicity: перевод из двух UPDATE либо применяется целиком, либо не применяется вовсе.
-- Ошибки в этом файле ожидаемые, поэтому psql не останавливается на них.
\set ON_ERROR_STOP off
CREATE EXTENSION IF NOT EXISTS pageinspect;
DROP TABLE IF EXISTS accounts CASCADE;
CREATE TABLE accounts (
    id      int PRIMARY KEY,
    owner   text NOT NULL,
    balance numeric(12,2) NOT NULL
);
INSERT INTO accounts VALUES (1, 'alice', 100), (2, 'bob', 50);

\echo '--- 1.1 до перевода'
SELECT id, owner, balance FROM accounts ORDER BY id;

\echo '--- 1.2 перевод 30 от alice к bob, ошибка после первого UPDATE'
BEGIN;
SELECT pg_current_xact_id() AS failed_xid \gset
UPDATE accounts SET balance = balance - 30 WHERE id = 1;
-- внутри транзакции списание уже видно
SELECT id, balance FROM accounts ORDER BY id;
-- имитация сбоя приложения посреди перевода
SELECT 1 / 0;
-- после ошибки транзакция в состоянии aborted, любые команды отвергаются
UPDATE accounts SET balance = balance + 30 WHERE id = 2;
-- COMMIT в такой транзакции сервер выполняет как ROLLBACK
COMMIT;

\echo '--- 1.3 после неудачного перевода балансы не изменились'
SELECT id, owner, balance FROM accounts ORDER BY id;
SELECT :'failed_xid' AS failed_xid, pg_xact_status(:'failed_xid'::xid8) AS status;

\echo '--- 1.4 версия строки от отменённой транзакции физически лежит на странице, но невидима'
SELECT lp, t_xmin, t_xmax, t_ctid
FROM heap_page_items(get_raw_page('accounts', 0))
ORDER BY lp;

\echo '--- 1.5 SAVEPOINT: откат части транзакции без потери остального'
BEGIN;
UPDATE accounts SET balance = balance - 10 WHERE id = 1;
SAVEPOINT before_bonus;
UPDATE accounts SET balance = balance + 1000 WHERE id = 2;
ROLLBACK TO SAVEPOINT before_bonus;
UPDATE accounts SET balance = balance + 10 WHERE id = 2;
COMMIT;
SELECT id, owner, balance FROM accounts ORDER BY id;
