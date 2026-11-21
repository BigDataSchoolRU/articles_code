# duckdb==2.0.0 | sqlite3 из стандартной библиотеки | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 5. Один и тот же агрегат в DuckDB и SQLite на одной машине.

SQLite не читает Parquet, поэтому данные сначала грузятся в таблицу.
Грузим только 6 столбцов, нужных запросу, это в пользу SQLite.
Время запроса берём лучшее из 3 прогонов. Цифры верны только для этой машины.
"""
import sqlite3
import time
from pathlib import Path

import duckdb

PARQUET = "data/orders.parquet"
SQLITE_DB = "data/orders.sqlite"
COLS = "region, category, quantity, price, discount, status"
AGG = """
SELECT region, category, count(*) AS orders,
       sum(quantity * price * (1 - discount)) AS revenue
FROM {src}
WHERE status <> 'cancelled'
GROUP BY region, category
ORDER BY region, category
"""


def best_of(fn, runs: int = 3):
    best, res = float("inf"), None
    for _ in range(runs):
        t0 = time.perf_counter()
        res = fn()
        best = min(best, time.perf_counter() - t0)
    return best, res


rows = []  # (вариант, загрузка, запрос)

# --- DuckDB по файлу, без загрузки
con = duckdb.connect()
t_q, duck_res = best_of(lambda: con.sql(AGG.format(src=f"read_parquet('{PARQUET}')")).fetchall())
rows.append(("DuckDB, read_parquet по файлу", None, t_q))

# --- DuckDB, таблица в памяти
t0 = time.perf_counter()
con.execute(f"CREATE TABLE orders AS SELECT {COLS} FROM read_parquet('{PARQUET}')")
t_load = time.perf_counter() - t0
t_q, _ = best_of(lambda: con.sql(AGG.format(src="orders")).fetchall())
rows.append(("DuckDB, таблица в памяти", t_load, t_q))

# --- Тот же запрос в один поток: сколько даёт параллелизм
con.execute("SET threads = 1")
t_q, _ = best_of(lambda: con.sql(AGG.format(src="orders")).fetchall())
rows.append(("DuckDB, таблица, threads=1", None, t_q))
con.execute("RESET threads")

# --- SQLite: загрузка батчами из DuckDB, затем тот же агрегат
Path(SQLITE_DB).unlink(missing_ok=True)
sq = sqlite3.connect(SQLITE_DB)
sq.execute("PRAGMA journal_mode = OFF")
sq.execute("PRAGMA synchronous = OFF")
sq.execute(
    "CREATE TABLE orders (region TEXT, category TEXT, quantity INTEGER, "
    "price REAL, discount REAL, status TEXT)"
)
t0 = time.perf_counter()
cur = con.execute(f"SELECT {COLS} FROM read_parquet('{PARQUET}')")
while True:
    batch = cur.fetchmany(100_000)
    if not batch:
        break
    sq.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", batch)
sq.commit()
t_load = time.perf_counter() - t0
t_q, sqlite_res = best_of(lambda: sq.execute(AGG.format(src="orders")).fetchall())
rows.append(("SQLite, таблица в файле", t_load, t_q))
sq.close()
con.close()

# Сверка результатов двух движков
same = len(duck_res) == len(sqlite_res) and all(
    a[:3] == b[:3] and abs(a[3] - b[3]) < 0.01 for a, b in zip(duck_res, sqlite_res)
)

print(f"{'вариант':<40}{'загрузка, с':>12}{'запрос, с':>20}")
for name, load, q in rows:
    load_s = "-" if load is None else f"{load:.2f}"
    print(f"{name:<40}{load_s:>12}{q:>20.4f}")
print(f"Результаты DuckDB и SQLite совпали: {same}, групп: {len(duck_res)}")
print(f"Размер файла SQLite: {Path(SQLITE_DB).stat().st_size / 1024 / 1024:.1f} MB ({SQLITE_DB})")
print("Это одна машина и один набор данных, обобщать на другие нагрузки нельзя")
if not same:
    raise SystemExit(1)
