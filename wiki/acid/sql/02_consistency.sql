-- postgres 18.6 в Docker, прогнано на стенде 2026-11-05
-- Consistency: ограничения схемы не дают зафиксировать недопустимое состояние.
-- Ошибки в этом файле ожидаемые, поэтому psql не останавливается на них.
\set ON_ERROR_STOP off
DROP TABLE IF EXISTS transfers, accounts CASCADE;
CREATE TABLE accounts (
    id      int PRIMARY KEY,
    owner   text NOT NULL,
    balance numeric(12,2) NOT NULL CHECK (balance >= 0)
);
-- внешние ключи объявлены откладываемыми: по умолчанию проверяются сразу,
-- но внутри транзакции проверку можно перенести на COMMIT
CREATE TABLE transfers (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_id int NOT NULL REFERENCES accounts (id) DEFERRABLE INITIALLY IMMEDIATE,
    to_id   int NOT NULL REFERENCES accounts (id) DEFERRABLE INITIALLY IMMEDIATE,
    amount  numeric(12,2) NOT NULL CHECK (amount > 0)
);
INSERT INTO accounts VALUES (1, 'alice', 100), (2, 'bob', 50);

\echo '--- 2.1 перевод 150 при балансе 100: CHECK (balance >= 0) отменяет всю транзакцию'
BEGIN;
INSERT INTO transfers (from_id, to_id, amount) VALUES (1, 2, 150);
UPDATE accounts SET balance = balance + 150 WHERE id = 2;
UPDATE accounts SET balance = balance - 150 WHERE id = 1;
COMMIT;
SELECT id, owner, balance FROM accounts ORDER BY id;
SELECT count(*) AS transfers_rows FROM transfers;

\echo '--- 2.2 перевод на несуществующий счёт: внешний ключ проверяется сразу'
INSERT INTO transfers (from_id, to_id, amount) VALUES (1, 99, 10);

\echo '--- 2.3 отложенная проверка: перевод раньше счёта, счёт создан до COMMIT'
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
INSERT INTO transfers (from_id, to_id, amount) VALUES (1, 3, 10);
INSERT INTO accounts VALUES (3, 'carol', 0);
UPDATE accounts SET balance = balance - 10 WHERE id = 1;
UPDATE accounts SET balance = balance + 10 WHERE id = 3;
COMMIT;
SELECT id, owner, balance FROM accounts ORDER BY id;

\echo '--- 2.4 отложенная проверка: счёт так и не создан, ошибка приходит на COMMIT'
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
INSERT INTO transfers (from_id, to_id, amount) VALUES (1, 4, 10);
SELECT count(*) AS transfers_inside_txn FROM transfers;
COMMIT;
SELECT count(*) AS transfers_rows FROM transfers;
