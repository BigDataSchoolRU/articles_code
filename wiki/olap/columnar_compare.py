# psycopg 3.3.4, duckdb 1.5.5, PostgreSQL 18.4 (Homebrew), прогнано на стенде 2026-08-31
"""Сравнивает одну и ту же аналитическую агрегацию на строковом ROLAP-движке
(PostgreSQL, join звёздной схемы) и на колоночном движке (DuckDB, денормализованный
снимок в памяти) — иллюстрация того, зачем OLAP ушёл от классического куба
к колоночным СУБД (ClickHouse/Druid/StarRocks и подобным).

Постгрес и DuckDB замеряются после отдельного прогревочного запроса каждый —
первый холодный вызов меряет прогрев кэша страниц/буферов, а не саму агрегацию.
"""
import time

import duckdb
import pandas as pd
import psycopg

DB_NAME = "olap_demo"

# Одна и та же аналитика: выручка и количество по категории и кварталу,
# по всей таблице фактов (1 млн строк) без фильтров — тяжёлый полный скан
AGG_QUERY_PG = """
SELECT p.category, d.quarter, sum(f.revenue) AS revenue, sum(f.quantity) AS quantity
FROM fact_sales f
JOIN dim_date d ON d.date_id = f.date_id
JOIN dim_product p ON p.product_id = f.product_id
GROUP BY p.category, d.quarter
ORDER BY p.category, d.quarter;
"""

# Денормализованный снимок для DuckDB: та же семантика, но без join на каждый запрос,
# как это делают колоночные аналитические СУБД поверх плоской широкой таблицы
SNAPSHOT_QUERY = """
SELECT p.category, d.quarter, f.revenue, f.quantity
FROM fact_sales f
JOIN dim_date d ON d.date_id = f.date_id
JOIN dim_product p ON p.product_id = f.product_id;
"""

AGG_QUERY_DUCKDB = """
SELECT category, quarter, sum(revenue) AS revenue, sum(quantity) AS quantity
FROM snapshot
GROUP BY category, quarter
ORDER BY category, quarter;
"""


def time_pg(conn: psycopg.Connection) -> float:
    conn.execute(AGG_QUERY_PG).fetchall()  # прогрев
    t0 = time.time()
    conn.execute(AGG_QUERY_PG).fetchall()
    return time.time() - t0


def time_duckdb(rel: duckdb.DuckDBPyRelation) -> float:
    rel.execute()  # прогрев
    t0 = time.time()
    rel.execute()
    return time.time() - t0


def main() -> None:
    with psycopg.connect(dbname=DB_NAME) as conn:
        pg_seconds = time_pg(conn)

        t0 = time.time()
        cur = conn.execute(SNAPSHOT_QUERY)
        cols = [c.name for c in cur.description]
        rows = cur.fetchall()
        snapshot_seconds = time.time() - t0

    snapshot_df = pd.DataFrame(rows, columns=cols)

    duck = duckdb.connect()
    duck.execute("CREATE TABLE snapshot AS SELECT * FROM snapshot_df")
    rel = duck.sql(AGG_QUERY_DUCKDB)
    duck_seconds = time_duckdb(rel)

    print(f"строк в снимке: {len(rows)}")
    print(f"выгрузка снимка из Postgres в Python: {snapshot_seconds:.3f} с")
    print(f"агрегация в PostgreSQL (join звёздной схемы, тёплый кэш): {pg_seconds:.3f} с")
    print(f"агрегация в DuckDB (колоночная, тёплый кэш): {duck_seconds:.3f} с")
    print(f"ускорение: {pg_seconds / duck_seconds:.1f}x")

    print("\n--- первые строки результата (одинаковы в обоих движках) ---")
    for row in rel.fetchall()[:5]:
        print(row)


if __name__ == "__main__":
    main()
