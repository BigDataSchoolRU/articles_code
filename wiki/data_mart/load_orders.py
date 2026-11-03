# duckdb 2.0.0, прогнано на стенде 2026-11-03
"""Имитация EL-загрузки: кладёт партию заказов в сырой слой raw хранилища DuckDB.

Запуск: python load_orders.py 1   (первая партия, слой raw создаётся заново)
        python load_orders.py 2   (догрузка: новые дни и один опоздавший заказ)
"""
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB = HERE / "warehouse.duckdb"

batch = int(sys.argv[1]) if len(sys.argv) > 1 else 1
con = duckdb.connect(str(DB))
con.execute("CREATE SCHEMA IF NOT EXISTS raw")

if batch == 1:
    # Первая загрузка: справочник клиентов и заказы с нуля
    con.execute("CREATE OR REPLACE TABLE raw.customers AS SELECT * FROM read_csv_auto(?)",
                [str(HERE / "data" / "customers.csv")])
    con.execute("CREATE OR REPLACE TABLE raw.orders AS SELECT * FROM read_csv_auto(?)",
                [str(HERE / "data" / "orders_batch1.csv")])
else:
    # Догрузка: дописываем строки, как это делает ежедневный EL-конвейер
    con.execute("INSERT INTO raw.orders SELECT * FROM read_csv_auto(?)",
                [str(HERE / "data" / f"orders_batch{batch}.csv")])

rows, last_day = con.execute("SELECT count(*), max(order_date) FROM raw.orders").fetchone()
print(f"партия {batch}: в raw.orders строк={rows}, последний день={last_day}")
con.close()
