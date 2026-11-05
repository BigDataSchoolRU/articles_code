-- postgres 18.6, прогнано на стенде 2026-11-05: подтверждённые транзакции перед аварийной остановкой
\pset footer off
DROP TABLE IF EXISTS payments, payments_unlogged;
CREATE TABLE payments (id int PRIMARY KEY, amount numeric);
CREATE UNLOGGED TABLE payments_unlogged (id int PRIMARY KEY, amount numeric);

-- контрольная точка, от её точки REDO сервер начнёт проигрывать журнал после сбоя
CHECKPOINT;
SELECT checkpoint_lsn, redo_lsn FROM pg_control_checkpoint();

-- пять отдельных транзакций, каждая подтверждена COMMIT; контрольных точек после них нет
INSERT INTO payments SELECT g, 10 FROM generate_series(1, 2000) g;
INSERT INTO payments SELECT g, 10 FROM generate_series(2001, 4000) g;
INSERT INTO payments SELECT g, 10 FROM generate_series(4001, 6000) g;
INSERT INTO payments SELECT g, 10 FROM generate_series(6001, 8000) g;
INSERT INTO payments SELECT g, 10 FROM generate_series(8001, 10000) g;
INSERT INTO payments_unlogged SELECT g, 10 FROM generate_series(1, 10000) g;

SELECT (SELECT count(*) FROM payments) AS payments,
       (SELECT count(*) FROM payments_unlogged) AS payments_unlogged,
       pg_current_wal_lsn() AS lsn_at_crash;
