-- вторая нагрузка: тот же набор операций на таблице с REPLICA IDENTITY FULL
INSERT INTO orders (customer, status, amount) VALUES ('umbrella', 'new', 777.25);
UPDATE orders SET status = 'shipped', amount = 800.00 WHERE customer = 'umbrella';
DELETE FROM orders WHERE customer = 'acme';
