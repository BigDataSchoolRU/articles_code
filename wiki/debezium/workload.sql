-- нагрузка на таблицу orders: по одной операции каждого типа
INSERT INTO orders (customer, status, amount) VALUES ('initech', 'new', 4200.00);
UPDATE orders SET status = 'paid' WHERE customer = 'initech';
DELETE FROM orders WHERE customer = 'globex';
