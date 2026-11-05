-- postgres 18.6 в Docker, прогнано на стенде 2026-11-05
-- Durability: подтверждённые транзакции перед аварийной остановкой сервера.
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, note text NOT NULL);
SHOW synchronous_commit;
SHOW fsync;
-- пять отдельных транзакций, каждая получила от сервера COMMIT
INSERT INTO orders (note) VALUES ('подтверждён 1');
INSERT INTO orders (note) VALUES ('подтверждён 2');
INSERT INTO orders (note) VALUES ('подтверждён 3');
INSERT INTO orders (note) VALUES ('подтверждён 4');
INSERT INTO orders (note) VALUES ('подтверждён 5');
SELECT count(*) AS committed_rows FROM orders;
