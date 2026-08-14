-- схема демо-базы, выполняется один раз при создании контейнера postgres:18
CREATE TABLE orders (
    id      serial PRIMARY KEY,
    customer text NOT NULL,
    status   text NOT NULL,
    amount   numeric(10,2) NOT NULL
);

-- две строки лежат в таблице до старта коннектора: их заберёт начальный снимок
INSERT INTO orders (customer, status, amount) VALUES
    ('acme',   'new',  1500.00),
    ('globex', 'paid',  980.50);
