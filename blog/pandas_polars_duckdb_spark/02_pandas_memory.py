# pandas==3.0.6, pyarrow==25.0.1, psutil==7.1.3 | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; замер по мотивам habr.com/ru/articles/1087386
"""Сколько памяти pandas тратит на сжатый колоночный Parquet и что даёт columns=[...].

pandas работает eager: read_parquet разворачивает каждое значение в память целиком.
Скрипт меряет размер DataFrame для разных наборов колонок и экстраполирует на large.
"""
import gc
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import pandas as pd
import psutil
import pyarrow.parquet as pq

SMALL = "data/orders_small.parquet"
LARGE = "data/orders_large.parquet"
BUDGET_MB = 2048
MB = 2**20

CASES = [
    ("все колонки", {}),
    ("6 колонок (filter+join+groupby)", {"columns": ["product_id", "ts", "status", "qty", "price", "discount"]}),
    ("3 колонки (только join)", {"columns": ["product_id", "qty", "price"]}),
    ("все колонки, dtype_backend=pyarrow", {"dtype_backend": "pyarrow"}),
]


def main() -> None:
    if not Path(SMALL).exists():
        raise SystemExit(f"нет {SMALL}: сначала запустите 01_gen_data.py")
    proc = psutil.Process()
    disk_mb = os.path.getsize(SMALL) / MB
    rows = pq.ParquetFile(SMALL).metadata.num_rows
    print(f"pandas {pd.__version__}, {SMALL}: {rows:,} строк, {disk_mb:.0f} МБ на диске")
    print(f"{'вариант':38} {'DataFrame, МБ':>14} {'x к диску':>10} {'прирост RSS, МБ':>16}")

    per_row = {}
    for label, kwargs in CASES:
        gc.collect()
        rss0 = proc.memory_info().rss
        df = pd.read_parquet(SMALL, **kwargs)
        # deep=True считает и содержимое строк, а не только указатели
        mem = df.memory_usage(deep=True).sum() / MB
        rss1 = proc.memory_info().rss
        per_row[label] = mem * MB / rows
        print(f"{label:38} {mem:14.0f} {mem / disk_mb:10.1f} {(rss1 - rss0) / MB:16.0f}")
        if not kwargs:
            print("  dtypes:", ", ".join(f"{c}:{t}" for c, t in df.dtypes.items()))
        del df

    print("В pandas 3.0 строки по умолчанию уже хранятся в Arrow, поэтому dtype_backend=pyarrow почти ничего не меняет")

    if Path(LARGE).exists():
        large_rows = pq.ParquetFile(LARGE).metadata.num_rows
        print(f"Экстраполяция на {LARGE} ({large_rows:,} строк), бюджет {BUDGET_MB} МБ.")
        print("Фильтр и merge создают копии, поэтому безопасный порог около половины бюджета:")
        for label, _ in CASES[:3]:
            est = per_row[label] * large_rows / MB
            verdict = "влезает" if est < BUDGET_MB * 0.5 else "впритык или OOM"
            print(f"  {label:36} ~{est:6.0f} МБ -> {verdict}")


if __name__ == "__main__":
    main()
