# PostgreSQL 18.4 (Homebrew), psycopg 3.3.4, прогнано на стенде 2026-08-30
"""
Создаёт демо-базу data_quality_demo с таблицей orders (5000 строк) и намеренными
дефектами качества данных: дубли order_id, NULL в обязательных полях, отрицательные
суммы, некорректный формат email, разнобой регистра в status, даты заказа в будущем.
Скрипт идемпотентен: базу можно удалять, повторный запуск пересоздаёт её с нуля.
"""

import random
from datetime import date, timedelta

import psycopg

DB_NAME = "data_quality_demo"
ADMIN_DSN = "dbname=postgres user=techfriends host=localhost"
DEMO_DSN = f"dbname={DB_NAME} user=techfriends host=localhost"
TOTAL_ROWS = 5000
DUPLICATE_IDS = 30
NULL_EMAIL_ROWS = 26
NULL_AMOUNT_ROWS = 26
NEGATIVE_AMOUNT_ROWS = 20
BAD_EMAIL_ROWS = 15
CASE_MISMATCH_ROWS = 40
FUTURE_DATE_ROWS = 12

STATUS_VARIANTS = {
    "paid": ["paid", "PAID", "Paid"],
    "pending": ["pending", "PENDING"],
    "cancelled": ["cancelled", "Cancelled"],
}


def ensure_database() -> None:
    # CREATE DATABASE не идёт внутри транзакции, поэтому подключение в autocommit
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        exists = conn.execute(
            "select 1 from pg_database where datname = %s", (DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(f"create database {DB_NAME}")


def build_rows() -> list[tuple]:
    random.seed(42)
    base_date = date(2026, 1, 1)
    rows = []
    for i in range(1, TOTAL_ROWS + 1):
        order_id = i
        email = f"user{i}@example.com"
        amount = round(random.uniform(10, 5000), 2)
        status_key = random.choice(list(STATUS_VARIANTS))
        status = STATUS_VARIANTS[status_key][0]
        order_date = base_date + timedelta(days=random.randint(0, 240))
        rows.append([order_id, email, amount, status, order_date])

    # дубли order_id: копируем id соседней строки, остальные поля живые
    for i in random.sample(range(TOTAL_ROWS), DUPLICATE_IDS):
        rows[i][0] = rows[(i + 1) % TOTAL_ROWS][0]

    # полнота (completeness): пропуски в обязательных полях
    for i in random.sample(range(TOTAL_ROWS), NULL_EMAIL_ROWS):
        rows[i][1] = None
    for i in random.sample(range(TOTAL_ROWS), NULL_AMOUNT_ROWS):
        rows[i][2] = None

    # валидность (validity): сумма вне допустимого диапазона
    for i in random.sample(range(TOTAL_ROWS), NEGATIVE_AMOUNT_ROWS):
        if rows[i][2] is not None:
            rows[i][2] = -abs(rows[i][2])

    # валидность (validity): email не проходит формат адреса
    for i in random.sample(range(TOTAL_ROWS), BAD_EMAIL_ROWS):
        if rows[i][1] is not None:
            rows[i][1] = "not-an-email"

    # согласованность (consistency): один и тот же статус в разном регистре
    mismatch_idx = random.sample(range(TOTAL_ROWS), CASE_MISMATCH_ROWS)
    for i in mismatch_idx:
        key = next(k for k, variants in STATUS_VARIANTS.items() if rows[i][3] == variants[0])
        rows[i][3] = random.choice(STATUS_VARIANTS[key][1:])

    # своевременность (timeliness): дата заказа в будущем относительно дня прогона
    today = date.today()
    for i in random.sample(range(TOTAL_ROWS), FUTURE_DATE_ROWS):
        rows[i][4] = today + timedelta(days=random.randint(1, 30))

    return [tuple(r) for r in rows]


def load_rows(rows: list[tuple]) -> None:
    with psycopg.connect(DEMO_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("drop table if exists orders")
            cur.execute(
                """
                create table orders (
                    order_id integer,
                    customer_email text,
                    amount numeric(10, 2),
                    status text,
                    order_date date
                )
                """
            )
            with cur.copy(
                "copy orders (order_id, customer_email, amount, status, order_date) from stdin"
            ) as copy:
                for row in rows:
                    copy.write_row(row)
        conn.commit()


if __name__ == "__main__":
    ensure_database()
    demo_rows = build_rows()
    load_rows(demo_rows)
    print(f"orders: {len(demo_rows)} строк загружено в базу {DB_NAME}")
