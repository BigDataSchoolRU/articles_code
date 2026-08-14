-- PostgreSQL 18.4 (Homebrew), REPLICA IDENTITY FULL, прогон на стенде 2026-08-14
-- запускается после cdc_slot_demo.sql: таблица orders и слот уже созданы там

-- шаг 1: просим базу класть в журнал полную старую версию строки
ALTER TABLE orders REPLICA IDENTITY FULL;

-- шаг 2: повторяем тот же сценарий на второй строке
INSERT INTO orders VALUES (2, 'АО Василёк', 'new', 990.00);
UPDATE orders SET status = 'paid', amount = 1090.00 WHERE id = 2;
DELETE FROM orders WHERE id = 2;

-- шаг 3: теперь в UPDATE едет old-key целиком, а в DELETE все колонки строки
SELECT data FROM pg_logical_slot_get_changes('cdc_demo_slot', NULL, NULL);
