#!/usr/bin/env python3
# psycopg 3.3.4, PostgreSQL 18.4 (Homebrew), прогнано на стенде 2026-08-26
# Пересоздаёт демо-базу semantic_layer_demo с таблицей orders на 2000 строк.
# Безопасно перезапускать: база и таблица дропаются и создаются заново.
import random
from datetime import date, timedelta

import psycopg

ADMIN_DSN = "dbname=postgres"
DB_NAME = "semantic_layer_demo"

STATUSES = ["completed", "pending", "cancelled", "refunded"]
REGIONS = ["north", "south", "east", "west"]


def recreate_database() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        conn.execute(f"CREATE DATABASE {DB_NAME}")


def seed_orders(rows: int = 2000) -> None:
    with psycopg.connect(f"dbname={DB_NAME}", autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE orders (
                order_id     SERIAL PRIMARY KEY,
                customer_id  INTEGER NOT NULL,
                order_date   DATE NOT NULL,
                region       TEXT NOT NULL,
                status       TEXT NOT NULL,
                amount       NUMERIC(10, 2) NOT NULL
            )
            """
        )
        start = date(2025, 1, 1)
        batch = []
        for i in range(rows):
            order_date = start + timedelta(days=random.randint(0, 599))
            batch.append(
                (
                    random.randint(1, 300),
                    order_date,
                    random.choice(REGIONS),
                    random.choice(STATUSES),
                    round(random.uniform(9.90, 899.90), 2),
                )
            )
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO orders (customer_id, order_date, region, status, amount)
                VALUES (%s, %s, %s, %s, %s)
                """,
                batch,
            )


if __name__ == "__main__":
    recreate_database()
    seed_orders()
    print(f"База {DB_NAME} создана, таблица orders заполнена.")
