# duckdb==2.0.0, pandas==2.3.3 | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 3. SQL прямо по файлам: read_parquet и read_csv без загрузки в базу, результат в pandas DataFrame."""
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import CSV, PARQUET, ensure_data, q  # noqa: E402

AGG_SQL = """
SELECT region,
       category,
       count(*)                    AS orders,
       round(sum(amount * qty), 2) AS revenue,
       round(avg(amount), 2)       AS avg_amount
FROM {src}
WHERE ts >= TIMESTAMP '2026-06-01'
GROUP BY region, category
ORDER BY revenue DESC
"""


def main() -> int:
    ensure_data()
    con = duckdb.connect()

    # read_csv сам определяет разделитель, заголовок и типы столбцов
    print("Схема, которую read_csv вывел автоматически:")
    print(con.sql(f"DESCRIBE SELECT * FROM read_csv('{q(CSV)}')").df()[["column_name", "column_type"]].to_string(index=False))

    sources = [
        ("parquet", f"read_parquet('{q(PARQUET)}')"),
        ("csv", f"read_csv('{q(CSV)}')"),
    ]
    frames = {}
    for label, src in sources:
        t0 = time.perf_counter()
        # .df() отдаёт результат сразу в pandas DataFrame
        df = con.sql(AGG_SQL.format(src=src)).df()
        dt = time.perf_counter() - t0
        frames[label] = df
        print(f"\n--- {label}: {dt:.3f} с, {len(df)} групп, тип результата {type(df).__module__}.{type(df).__name__}")
        print(df.head(10).to_string(index=False))

    # Сверка: оба файла содержат один набор, агрегаты должны совпасть
    merged = frames["parquet"].merge(frames["csv"], on=["region", "category"], suffixes=("_pq", "_csv"))
    same_groups = len(merged) == len(frames["parquet"]) == len(frames["csv"])
    same_counts = bool((merged["orders_pq"] == merged["orders_csv"]).all())
    max_diff = float((merged["revenue_pq"] - merged["revenue_csv"]).abs().max())
    print(f"\nСверка parquet и csv: группы совпали={same_groups}, counts совпали={same_counts}, max |revenue diff|={max_diff:.4f}")

    # Обратный путь: DataFrame регистрируется как представление и снова доступен из SQL
    con.register("agg", frames["parquet"])
    by_region = con.sql(
        "SELECT region, sum(orders) AS orders, round(sum(revenue), 2) AS revenue "
        "FROM agg GROUP BY region ORDER BY revenue DESC"
    ).df()
    print("\nSQL поверх pandas DataFrame (con.register):")
    print(by_region.to_string(index=False))

    ok = same_groups and same_counts and max_diff < 0.05 and isinstance(by_region, pd.DataFrame)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
