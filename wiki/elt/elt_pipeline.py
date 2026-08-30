# psycopg 3.3.4, PostgreSQL 18.4, прогнано на стенде 2026-08-29
"""Простой ELT-конвейер: Extract из source.orders, Load сырых строк как есть
в raw.orders_raw, Transform одним SQL-запросом внутри той же базы elt_demo
в analytics.sales_summary. База поднята db_setup.py.

Ключевой момент архитектуры виден прямо в коде: между extract и load нет
никакой обработки, pandas тут вообще нет, данные копируются построчно
как получены. Дедупликация, чистка region, отсев NULL и агрегация происходят
позже, одним запросом transform_sql, который выполняет сам Postgres после
загрузки. Это и есть ELT, трансформация это работа вычислительной мощности
целевого хранилища, а не отдельного процесса между извлечением и загрузкой.
В ETL то же самое сделал бы pandas ещё до load.
"""

import time

import psycopg

DSN = "host=localhost port=5432 dbname=elt_demo user=techfriends"

CREATE_RAW = """
CREATE SCHEMA IF NOT EXISTS raw;
DROP TABLE IF EXISTS raw.orders_raw;
CREATE TABLE raw.orders_raw (
    id          bigint,
    quantity    integer,
    unit_price  numeric(10,2),
    region      text,
    order_date  date,
    status      text
);
"""

# Один SQL-запрос, вся трансформация: детерминированная дедупликация по id,
# чистка региона, отсев брака, бизнес-фильтр по статусу, расчёт выручки и
# агрегация по региону и дате. Ничего из этого не покидает базу.
TRANSFORM_SQL = """
CREATE SCHEMA IF NOT EXISTS analytics;
DROP TABLE IF EXISTS analytics.sales_summary;
CREATE TABLE analytics.sales_summary (
    region        text          NOT NULL,
    order_date    date          NOT NULL,
    order_count   integer       NOT NULL,
    total_revenue numeric(12,2) NOT NULL,
    PRIMARY KEY (region, order_date)
);

INSERT INTO analytics.sales_summary (region, order_date, order_count, total_revenue)
WITH deduped AS (
    -- дубли от повторной выгрузки источника: одна строка на id
    SELECT DISTINCT ON (id) id, quantity, unit_price, region, order_date, status
    FROM raw.orders_raw
    ORDER BY id, ctid
),
cleaned AS (
    -- разнобой в region и пропуски в quantity/unit_price правятся здесь,
    -- а не на стороне источника или в промежуточном процессе
    SELECT
        initcap(trim(region)) AS region,
        order_date,
        quantity,
        unit_price::double precision AS unit_price
    FROM deduped
    WHERE quantity IS NOT NULL
      AND unit_price IS NOT NULL
      AND status = 'completed'
)
SELECT region, order_date, count(*) AS order_count,
       round(sum(quantity * unit_price)::numeric, 2) AS total_revenue
FROM cleaned
GROUP BY region, order_date;
"""


def extract_and_load(conn: psycopg.Connection) -> tuple[int, int]:
    """Extract: полная выгрузка source.orders без фильтров и очистки.
    Load: та же самая выгрузка построчно уходит в raw.orders_raw как есть,
    ни дублей, ни NULL, ни разнобоя в region никто не трогает."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, quantity, unit_price, region, order_date, status FROM source.orders")
        rows = cur.fetchall()
        extracted = len(rows)

        cur.execute(CREATE_RAW)
        cur.executemany(
            "INSERT INTO raw.orders_raw (id, quantity, unit_price, region, order_date, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
        loaded = cur.execute("SELECT count(*) FROM raw.orders_raw").fetchone()[0]
    conn.commit()
    return extracted, loaded


def transform(conn: psycopg.Connection) -> int:
    """Transform: один SQL-запрос выполняется внутри Postgres над уже
    загруженными сырыми данными и строит analytics.sales_summary."""
    with conn.cursor() as cur:
        cur.execute(TRANSFORM_SQL)
        summary_rows = cur.execute("SELECT count(*) FROM analytics.sales_summary").fetchone()[0]
    conn.commit()
    return summary_rows


if __name__ == "__main__":
    with psycopg.connect(DSN) as conn:
        t0 = time.time()
        extracted, loaded = extract_and_load(conn)
        t1 = time.time()
        summary_rows = transform(conn)
        t2 = time.time()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT region, order_date, order_count, total_revenue "
                "FROM analytics.sales_summary ORDER BY region, order_date LIMIT 10"
            )
            preview = cur.fetchall()

    print(f"extract: {extracted} строк -> load (как есть, без очистки): {loaded} строк в raw.orders_raw")
    print(f"transform (один SQL-запрос внутри базы): {summary_rows} строк в analytics.sales_summary")
    print(f"extract+load {t1 - t0:.3f} с, transform {t2 - t1:.3f} с, итого {t2 - t0:.3f} с")
    print(f"{'region':<8} {'order_date':<12} {'order_count':<12} total_revenue")
    for region, order_date, order_count, total_revenue in preview:
        print(f"{region:<8} {str(order_date):<12} {order_count:<12} {total_revenue}")
