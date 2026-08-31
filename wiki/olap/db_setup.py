# psycopg 3.3.4, PostgreSQL 18.4 (Homebrew), прогнано на стенде 2026-08-31
"""Пересоздаёт демо-базу olap_demo со звёздной схемой (факт продаж + три измерения).

Без сети и внешних сервисов: dropdb/createdb плюс SQL-генерация данных прямо в Postgres
(generate_series + random), без построчных INSERT из Python — на миллион строк факта
это на порядки быстрее, чем executemany.
"""
import subprocess
import time

import psycopg

PG_BIN = "/opt/homebrew/opt/postgresql@18/bin"
DB_NAME = "olap_demo"

DDL = """
CREATE TABLE dim_date (
    date_id     serial PRIMARY KEY,
    full_date   date NOT NULL,
    year        int NOT NULL,
    quarter     int NOT NULL,
    month       int NOT NULL,
    month_name  text NOT NULL,
    day_of_week text NOT NULL
);

CREATE TABLE dim_product (
    product_id   serial PRIMARY KEY,
    product_name text NOT NULL,
    category     text NOT NULL,
    subcategory  text NOT NULL
);

CREATE TABLE dim_store (
    store_id   serial PRIMARY KEY,
    store_name text NOT NULL,
    region     text NOT NULL,
    country    text NOT NULL
);

CREATE TABLE fact_sales (
    sale_id    bigserial PRIMARY KEY,
    date_id    int NOT NULL REFERENCES dim_date(date_id),
    product_id int NOT NULL REFERENCES dim_product(product_id),
    store_id   int NOT NULL REFERENCES dim_store(store_id),
    quantity   int NOT NULL,
    revenue    numeric(10, 2) NOT NULL
);
"""

# 730 дней (2024-2025), детерминированно от даты начала
FILL_DIM_DATE = """
INSERT INTO dim_date (full_date, year, quarter, month, month_name, day_of_week)
SELECT
    d::date,
    extract(year FROM d)::int,
    extract(quarter FROM d)::int,
    extract(month FROM d)::int,
    to_char(d, 'TMMonth'),
    to_char(d, 'TMDay')
FROM generate_series('2024-01-01'::date, '2025-12-31'::date, '1 day'::interval) AS d;
"""

CATEGORIES = ["Electronics", "Clothing", "Home", "Sports", "Books", "Toys"]

FILL_DIM_PRODUCT = """
INSERT INTO dim_product (product_name, category, subcategory)
SELECT
    cat || ' Item ' || n,
    cat,
    cat || ' Sub ' || ((n - 1) %% 3 + 1)
FROM unnest(%s::text[]) AS cat, generate_series(1, 10) AS n;
"""

REGIONS = ["North", "South", "East", "West", "Central"]

FILL_DIM_STORE = """
INSERT INTO dim_store (store_name, region, country)
SELECT
    reg || ' Store ' || n,
    reg,
    'RU'
FROM unnest(%s::text[]) AS reg, generate_series(1, 5) AS n;
"""

# random() внутри SELECT-списка вычисляется на каждую строку (VOLATILE),
# в отличие от подзапроса-агрегата — здесь ловушка pgvector-демо не повторяется.
SET_SEED = "SELECT setseed(0.42);"

FILL_FACT_SALES = """
INSERT INTO fact_sales (date_id, product_id, store_id, quantity, revenue)
SELECT
    1 + (random() * 729)::int,
    1 + (random() * 59)::int,
    1 + (random() * 24)::int,
    1 + (random() * 9)::int,
    round((10 + random() * 490)::numeric, 2)
FROM generate_series(1, %s);
"""


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main() -> None:
    run([f"{PG_BIN}/dropdb", "--if-exists", DB_NAME])
    run([f"{PG_BIN}/createdb", DB_NAME])

    with psycopg.connect(dbname=DB_NAME, autocommit=True) as conn:
        conn.execute(DDL)
        conn.execute(FILL_DIM_DATE)
        conn.execute(FILL_DIM_PRODUCT, (CATEGORIES,))
        conn.execute(FILL_DIM_STORE, (REGIONS,))

        conn.execute(SET_SEED)
        t0 = time.time()
        conn.execute(FILL_FACT_SALES, (1_000_000,))
        elapsed = time.time() - t0

        counts = conn.execute(
            "SELECT (SELECT count(*) FROM dim_date), (SELECT count(*) FROM dim_product), "
            "(SELECT count(*) FROM dim_store), (SELECT count(*) FROM fact_sales)"
        ).fetchone()

    print(f"fact_sales: 1 000 000 строк за {elapsed:.2f} с")
    print(f"dim_date={counts[0]}, dim_product={counts[1]}, dim_store={counts[2]}, fact_sales={counts[3]}")


if __name__ == "__main__":
    main()
