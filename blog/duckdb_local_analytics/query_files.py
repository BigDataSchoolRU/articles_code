# duckdb==2.0.0, pandas==2.3.3 | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 3. SQL прямо по файлам: read_parquet и read_csv, агрегат с GROUP BY, результат в DataFrame.

Никакой загрузки в базу: DuckDB читает файлы в момент запроса.
"""
import time

import duckdb

SOURCES = {
    "parquet": "read_parquet('data/orders.parquet')",
    "csv": "read_csv('data/orders.csv')",
}

QUERY = """
SELECT region,
       category,
       count(*) AS orders,
       sum(quantity * price * (1 - discount)) AS revenue
FROM {src}
WHERE status <> 'cancelled'
GROUP BY region, category
ORDER BY region, category
"""

con = duckdb.connect()
results = {}
for name, src in SOURCES.items():
    t0 = time.perf_counter()
    # .df() отдаёт результат как pandas.DataFrame
    df = con.sql(QUERY.format(src=src)).df()
    elapsed = time.perf_counter() - t0
    results[name] = df
    kind = f"{type(df).__module__}.{type(df).__name__}"
    print(f"--- {name}: {elapsed:.3f} с, {len(df)} групп, тип результата {kind}")
    print(df.head(5).to_string(index=False))

# Схема, которую read_csv вывел автоматически
print("--- типы, выведенные read_csv:")
for col, typ in zip(*[con.sql("SELECT * FROM read_csv('data/orders.csv') LIMIT 0").__getattribute__(a) for a in ("columns", "types")]):
    print(f"  {col}: {typ}")

# Сверка: оба источника должны дать один и тот же ответ
p, c = results["parquet"], results["csv"]
m = p.merge(c, on=["region", "category"], suffixes=("_pq", "_csv"), how="outer")
groups_ok = len(m) == len(p) == len(c)
counts_ok = bool((m["orders_pq"] == m["orders_csv"]).all())
max_diff = float((m["revenue_pq"] - m["revenue_csv"]).abs().max())
print(f"Сверка parquet и csv: группы совпали={groups_ok}, counts совпали={counts_ok}, max |revenue diff|={max_diff:.4f}")
con.close()

if not (groups_ok and counts_ok and max_diff < 0.01):
    raise SystemExit(1)
