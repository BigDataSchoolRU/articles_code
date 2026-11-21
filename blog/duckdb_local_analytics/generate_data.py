# duckdb==2.0.0 | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 2. Генерируем синтетический набор заказов и пишем его в Parquet и CSV.

Данные детерминированы: значения считаются через hash(i, ...), а не random(),
поэтому повторный прогон даёт тот же набор. Заказы упорядочены по дате,
это важно для шага 4: статистика min/max по row group позволяет пропускать группы.
"""
import argparse
import time
from pathlib import Path

import duckdb

parser = argparse.ArgumentParser()
parser.add_argument("--rows", type=int, default=5_000_000)
args = parser.parse_args()
n = args.rows

Path("data").mkdir(exist_ok=True)
PARQUET = "data/orders.parquet"
CSV = "data/orders.csv"

con = duckdb.connect()

# Генерация прямо в COPY: строки не проходят через Python
gen_sql = f"""
COPY (
    SELECT
        i AS order_id,
        DATE '2024-01-01' + CAST(i * 730 // {n} AS INTEGER) AS order_date,
        CAST(hash(i, 'customer') % 200000 AS INTEGER) AS customer_id,
        ['north', 'south', 'east', 'west', 'center',
         'ural', 'siberia', 'volga', 'far_east', 'caucasus']
            [1 + CAST(hash(i, 'region') % 10 AS INTEGER)] AS region,
        'cat_' || lpad(CAST(hash(i, 'category') % 25 AS VARCHAR), 2, '0') AS category,
        CAST(hash(i, 'product') % 5000 AS INTEGER) AS product_id,
        CAST(1 + hash(i, 'qty') % 5 AS INTEGER) AS quantity,
        round(CAST(hash(i, 'price') % 100000 AS DOUBLE) / 100 + 1, 2) AS price,
        CAST(hash(i, 'disc') % 4 AS DOUBLE) * 0.05 AS discount,
        CASE hash(i, 'status') % 20
            WHEN 0 THEN 'cancelled'
            WHEN 1 THEN 'returned'
            ELSE 'delivered'
        END AS status,
        'note ' || CAST(hash(i, 'note') % 100000 AS VARCHAR) AS comment
    FROM range({n}) t(i)
) TO '{PARQUET}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880)
"""

t0 = time.perf_counter()
con.execute(gen_sql)
print(f"Parquet записан за {time.perf_counter() - t0:.2f} с")

# CSV делаем из того же Parquet, чтобы наборы были идентичны
t0 = time.perf_counter()
con.execute(f"COPY (SELECT * FROM read_parquet('{PARQUET}')) TO '{CSV}' (FORMAT csv, HEADER true)")
print(f"CSV записан за {time.perf_counter() - t0:.2f} с")


def scalar(sql: str):
    # В DuckDB 2.0 у relation нет fetchone(): берём первую строку из fetchall()
    return con.sql(sql).fetchall()[0][0]


rows = scalar(f"SELECT count(*) FROM read_parquet('{PARQUET}')")
row_groups = scalar(f"SELECT count(DISTINCT row_group_id) FROM parquet_metadata('{PARQUET}')")
cols = len(con.sql(f"SELECT * FROM read_parquet('{PARQUET}') LIMIT 0").columns)

print(f"Строк: {rows:,}".replace(",", " "))
print(f"Столбцов: {cols}, row groups в Parquet: {row_groups}")
for name, path in (("orders.parquet", PARQUET), ("orders.csv", CSV)):
    size_mb = Path(path).stat().st_size / 1024 / 1024
    print(f"{name + ':':<20}{size_mb:>6.1f} MB  ({path})")
con.close()
