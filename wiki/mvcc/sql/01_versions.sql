-- postgres 18.6 в Docker, pageinspect из contrib, прогнано на стенде 2026-11-06
-- Версии одной строки: что INSERT, UPDATE и DELETE оставляют на странице таблицы.
CREATE EXTENSION IF NOT EXISTS pageinspect;
DROP TABLE IF EXISTS accounts CASCADE;
-- автовакуум выключен, чтобы мёртвые версии не исчезли между шагами
CREATE TABLE accounts (
    id      int PRIMARY KEY,
    owner   text NOT NULL,
    balance numeric(12,2) NOT NULL
) WITH (autovacuum_enabled = off);

-- страница 0 таблицы глазами pageinspect: указатель, xmin, xmax, ссылка на следующую версию, флаги
\set page_items 'SELECT lp, lp_flags, t_xmin, t_xmax, t_ctid, f.raw_flags FROM heap_page_items(get_raw_page(''accounts'', 0)) h, LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) f ORDER BY lp'

\echo '--- 1.1 INSERT: одна версия, xmin = транзакция вставки, xmax = 0'
BEGIN;
SELECT pg_current_xact_id() AS insert_xid;
INSERT INTO accounts VALUES (1, 'alice', 100);
COMMIT;
SELECT xmin, xmax, ctid, id, balance FROM accounts;

\echo '--- 1.2 UPDATE: старая версия получает xmax, новая версия ложится рядом'
BEGIN;
SELECT pg_current_xact_id() AS update_xid;
UPDATE accounts SET balance = 70 WHERE id = 1;
COMMIT;
-- страница сразу после коммита, до первого чтения строки
:page_items;
-- запрос видит только одну версию
SELECT xmin, xmax, ctid, id, balance FROM accounts;
-- после чтения у версий появились подсказки XMIN_COMMITTED и XMAX_COMMITTED
:page_items;

\echo '--- 1.3 DELETE с откатом: xmax проставлен, но строка видна, потому что транзакция xmax отменена'
BEGIN;
SELECT pg_current_xact_id() AS rolled_back_delete_xid \gset
\echo rolled_back_delete_xid = :rolled_back_delete_xid
DELETE FROM accounts WHERE id = 1;
ROLLBACK;
SELECT xmin, xmax, ctid, id, balance FROM accounts;
SELECT pg_xact_status(:'rolled_back_delete_xid'::xid8) AS delete_status;

\echo '--- 1.4 DELETE с коммитом: строка не видна запросу, но версия осталась на странице'
BEGIN;
SELECT pg_current_xact_id() AS delete_xid;
DELETE FROM accounts WHERE id = 1;
COMMIT;
SELECT count(*) AS visible_rows FROM accounts;
:page_items;
