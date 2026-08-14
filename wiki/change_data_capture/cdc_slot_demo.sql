-- PostgreSQL 18.4 (Homebrew), плагин логического декодирования test_decoding
-- прогон на стенде 2026-08-14, полный вывод в run_output.txt

-- шаг 1: убираем следы прошлого прогона, скрипт должен запускаться повторно
SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots
 WHERE slot_name = 'cdc_demo_slot';
DROP TABLE IF EXISTS orders;

-- шаг 2: таблица-источник, за изменениями которой мы следим
CREATE TABLE orders (
    id       bigint PRIMARY KEY,
    customer text NOT NULL,
    status   text NOT NULL,
    amount   numeric(10,2) NOT NULL
);

-- шаг 3: слот репликации, он же точка чтения журнала и стоп-кран для его очистки
SELECT pg_create_logical_replication_slot('cdc_demo_slot', 'test_decoding');

-- шаг 4: обычная работа приложения, три операции в трёх транзакциях
INSERT INTO orders VALUES (1, 'ООО Ромашка', 'new', 1500.00);
UPDATE orders SET status = 'paid' WHERE id = 1;
DELETE FROM orders WHERE id = 1;

-- шаг 5: вычитываем поток изменений и сдвигаем позицию слота вперёд
SELECT lsn, xid, data FROM pg_logical_slot_get_changes('cdc_demo_slot', NULL, NULL);
