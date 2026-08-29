# pandas 3.0.5, psycopg 3.3.4, PostgreSQL 18.4, прогнано на стенде 2026-08-29
"""Простой ETL-конвейер: Extract из raw_orders, Transform в pandas, Load в
sales_summary — обе таблицы в одной базе etl_demo, поднятой db_setup.py.

Ключевой момент архитектуры виден прямо в коде: между extract() и load()
данные целиком проходят через процесс pandas, а не через SQL внутри базы.
Это и есть staging area классического ETL — трансформация происходит до
загрузки, вне хранилища. В ELT то же самое сделал бы SQL-запрос уже после
загрузки сырых данных в целевую таблицу.
"""

import time

import pandas as pd
import psycopg

DSN = "host=localhost port=5432 dbname=etl_demo user=techfriends"

CREATE_TARGET = """
DROP TABLE IF EXISTS sales_summary;
CREATE TABLE sales_summary (
    region        text          NOT NULL,
    order_date    date          NOT NULL,
    order_count   integer       NOT NULL,
    total_revenue numeric(12,2) NOT NULL,
    PRIMARY KEY (region, order_date)
);
"""


def extract(conn: psycopg.Connection) -> pd.DataFrame:
    """Extract: полная выгрузка исходной таблицы, без фильтров на стороне источника —
    вся логика отбора и очистки идёт дальше, в transform."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, quantity, unit_price::double precision AS unit_price, "
            "region, order_date, status FROM raw_orders"
        )
        rows = cur.fetchall()
        columns = [d.name for d in cur.description]
    return pd.DataFrame(rows, columns=columns)


def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Transform: базовая очистка, производный расчёт и агрегация — три вида
    трансформации из плана статьи, все на одном датафрейме."""
    extracted = len(df)

    # базовая очистка: дубли от повторной выгрузки источника, разнобой в
    # написании region, пропуски в полях, без которых нельзя посчитать выручку
    df = df.drop_duplicates(subset="id")
    df["region"] = df["region"].str.strip().str.title()
    df = df.dropna(subset=["quantity", "unit_price"])

    # бизнес-правило: в сводку идут только завершённые заказы
    df = df[df["status"] == "completed"]

    # производное вычисление: выручки в источнике нет, она считается здесь
    df["revenue"] = df["quantity"] * df["unit_price"]

    # агрегация: одна строка на регион и дату вместо одной на заказ
    summary = df.groupby(["region", "order_date"], as_index=False).agg(
        order_count=("id", "count"), total_revenue=("revenue", "sum")
    )

    print(
        f"extract: {extracted} строк -> после очистки и фильтра "
        f"status=completed: {len(df)} -> агрегировано в {len(summary)} строк"
    )
    return summary


def load(conn: psycopg.Connection, df: pd.DataFrame) -> None:
    """Load: full load — целевая таблица каждый раз очищается и наполняется
    заново целиком, без сравнения с предыдущим состоянием."""
    records = [
        (row.region, row.order_date, int(row.order_count), round(float(row.total_revenue), 2))
        for row in df.itertuples(index=False)
    ]
    with conn.cursor() as cur:
        cur.execute(CREATE_TARGET)
        cur.executemany(
            "INSERT INTO sales_summary (region, order_date, order_count, total_revenue) "
            "VALUES (%s, %s, %s, %s)",
            records,
        )
    conn.commit()


if __name__ == "__main__":
    with psycopg.connect(DSN) as conn:
        t0 = time.time()
        raw = extract(conn)
        t1 = time.time()
        summary = transform(raw)
        t2 = time.time()
        load(conn, summary)
        t3 = time.time()

    print(
        f"extract {t1 - t0:.3f} с, transform {t2 - t1:.3f} с, "
        f"load {t3 - t2:.3f} с, итого {t3 - t0:.3f} с"
    )
    print(summary.sort_values(["region", "order_date"]).head(10).to_string(index=False))
