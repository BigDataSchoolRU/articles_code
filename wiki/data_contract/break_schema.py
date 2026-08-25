# PostgreSQL 18.4, psycopg 3.3.4, прогнано на стенде 2026-08-25
"""Сценарий несовместимого изменения схемы на стороне продюсера.

Два изменения, которые в реальных проектах приезжают в релизе как безобидные:
сумму заказа переводят в text (условно «чтобы влезли валюты»), а колонку status
переименовывают в order_status. Данные при этом остаются на месте, запросы
частично работают, поэтому глазами такое не ловится. Контракт ловит.

После прогона схему возвращает обратно db_setup.py.
"""

import psycopg

DEMO_DSN = "host=localhost port=5432 dbname=contract_demo user=techfriends"

CHANGES = [
    ("сумма заказа numeric(10,2) -> text",
     "ALTER TABLE orders ALTER COLUMN order_amount TYPE text"),
    ("колонка status переименована в order_status",
     "ALTER TABLE orders RENAME COLUMN status TO order_status"),
]


def main() -> None:
    with psycopg.connect(DEMO_DSN, autocommit=True) as conn:
        for title, sql in CHANGES:
            conn.execute(sql)
            print(f"применено: {title}")
        cols = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'orders'
            ORDER BY ordinal_position
            """
        ).fetchall()
        rows = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    print(f"схема после изменения, строк по-прежнему {rows}:")
    for name, data_type in cols:
        print(f"  {name}: {data_type}")


if __name__ == "__main__":
    main()
