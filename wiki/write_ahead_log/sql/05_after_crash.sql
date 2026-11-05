-- postgres 18.6, прогнано на стенде 2026-11-05: что пережило сбой после проигрывания журнала
\pset footer off
SELECT (SELECT count(*) FROM payments) AS payments,
       (SELECT count(*) FROM payments_unlogged) AS payments_unlogged,
       (SELECT sum(amount) FROM payments) AS payments_sum;
SELECT checkpoint_lsn, redo_lsn FROM pg_control_checkpoint();
