# PostgreSQL 18.4, psycopg 3.3.4, прогнано на стенде 2026-08-25
"""Готовит демо-базу под контракт данных: создаёт базу contract_demo,
таблицу orders в исходной (совместимой с контрактом) схеме и наполняет её.

Скрипт идемпотентный: таблица каждый раз пересоздаётся, поэтому его можно
запускать сколько угодно раз, в том числе после сценария поломки схемы.
"""

import psycopg

# Локальный Homebrew-PostgreSQL, доверительная аутентификация по сокету.
ADMIN_DSN = "host=localhost port=5432 dbname=postgres user=techfriends"
DEMO_DSN = "host=localhost port=5432 dbname=contract_demo user=techfriends"

DDL = """
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
    id            bigint         PRIMARY KEY,
    customer_id   integer        NOT NULL,
    order_amount  numeric(10,2)  NOT NULL,
    status        text           NOT NULL,
    created_at    timestamptz    NOT NULL
);
"""

INSERT = """
INSERT INTO orders (id, customer_id, order_amount, status, created_at)
SELECT g,
       (random() * 500)::int + 1,
       round((random() * 9000 + 100)::numeric, 2),
       (ARRAY['new','paid','shipped','cancelled'])[(random() * 3)::int + 1],
       now() - (random() * 90) * interval '1 day'
FROM generate_series(1, 5000) AS g;
"""


def ensure_database() -> None:
    """Создаёт базу contract_demo, если её ещё нет. CREATE DATABASE не идёт
    внутри транзакции, поэтому подключение переводится в autocommit."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'contract_demo'"
        ).fetchone()
        if exists:
            print("база contract_demo уже есть")
        else:
            conn.execute("CREATE DATABASE contract_demo")
            print("база contract_demo создана")


def rebuild_table() -> None:
    """Пересоздаёт orders в схеме, которую описывает контракт, и наполняет её."""
    with psycopg.connect(DEMO_DSN, autocommit=True) as conn:
        conn.execute(DDL)
        conn.execute(INSERT)
        rows = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
        cols = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'orders'
            ORDER BY ordinal_position
            """
        ).fetchall()
    print(f"таблица orders пересоздана, строк: {rows}")
    for name, data_type in cols:
        print(f"  {name}: {data_type}")


if __name__ == "__main__":
    ensure_database()
    rebuild_table()
