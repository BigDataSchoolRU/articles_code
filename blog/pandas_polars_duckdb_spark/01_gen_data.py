# numpy==2.3.5, pyarrow==25.0.1 | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; синтетика по мотивам методики habr.com/ru/articles/1087386, это не официальный TPC-H
"""Генерирует синтетический датасет: факты заказов двух размеров и справочник товаров.

small (6 млн строк) помещается в бюджет 2 ГБ у всех движков,
large (30 млн строк) рассчитан на то, чтобы pandas упёрся в память.
Данные пишутся чанками, поэтому сам генератор памяти почти не ест.
"""
import argparse
import os
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

os.chdir(Path(__file__).resolve().parent)

DATA = Path("data")
N_PRODUCTS = 20_000
N_CUSTOMERS = 2_000_000
STATUSES = np.array(["NEW", "PAID", "SHIPPED", "CANCELLED"])
DISCOUNTS = np.array([0.0, 0.05, 0.1, 0.2], dtype=np.float32)
START = np.datetime64("2024-01-01T00:00:00", "us")
YEAR_US = 366 * 24 * 3600 * 1_000_000


def ready(path: Path, rows: int) -> bool:
    # Не перегенерируем, если файл уже есть и в нём нужное число строк
    if not path.exists():
        return False
    return pq.ParquetFile(path).metadata.num_rows == rows


def write_products(path: Path) -> None:
    rng = np.random.default_rng(7)
    categories = np.array([f"cat_{i:02d}" for i in range(40)])
    brands = np.array([f"brand_{i:03d}" for i in range(300)])
    table = pa.table({
        "product_id": pa.array(np.arange(1, N_PRODUCTS + 1, dtype=np.int32)),
        "category": pa.array(categories[rng.integers(0, len(categories), N_PRODUCTS)]),
        "brand": pa.array(brands[rng.integers(0, len(brands), N_PRODUCTS)]),
    })
    pq.write_table(table, path, compression="zstd")


def write_orders(path: Path, rows: int, seed: int, chunk: int = 1_000_000) -> None:
    rng = np.random.default_rng(seed)
    # Текстовая колонка нужна, чтобы показать разницу между диском и памятью у pandas
    comments = np.array([f"note-{i:05d}-" + "x" * (i % 24) for i in range(5000)], dtype=object)
    tmp = path.with_suffix(".tmp")
    writer = None
    written = 0
    while written < rows:
        n = min(chunk, rows - written)
        # Ключи распределены равномерно, перекосов нет: это ограничение синтетики
        ts = START + rng.integers(0, YEAR_US, n).astype("timedelta64[us]")
        table = pa.table({
            "order_id": pa.array(np.arange(written, written + n, dtype=np.int64)),
            "customer_id": pa.array(rng.integers(1, N_CUSTOMERS, n, dtype=np.int32)),
            "product_id": pa.array(rng.integers(1, N_PRODUCTS + 1, n, dtype=np.int32)),
            # Наивный timestamp без часового пояса: в Parquet это isAdjustedToUTC=false
            "ts": pa.array(ts, type=pa.timestamp("us")),
            "qty": pa.array(rng.integers(1, 20, n, dtype=np.int16)),
            "price": pa.array(np.round(rng.uniform(1, 500, n), 2)),
            "discount": pa.array(DISCOUNTS[rng.integers(0, len(DISCOUNTS), n)]),
            "status": pa.array(STATUSES[rng.integers(0, len(STATUSES), n)]),
            "comment": pa.array(comments[rng.integers(0, len(comments), n)]),
        })
        if writer is None:
            writer = pq.ParquetWriter(tmp, table.schema, compression="zstd")
        writer.write_table(table)
        written += n
    writer.close()
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--small-rows", type=int, default=6_000_000)
    parser.add_argument("--large-rows", type=int, default=30_000_000)
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)

    products = DATA / "products.parquet"
    if not ready(products, N_PRODUCTS):
        write_products(products)
    print(f"{products}: {N_PRODUCTS:,} строк, {products.stat().st_size / 2**20:.1f} МБ")

    for name, rows, seed in (("orders_small", args.small_rows, 1), ("orders_large", args.large_rows, 2)):
        path = DATA / f"{name}.parquet"
        t0 = time.perf_counter()
        if ready(path, rows):
            note = "уже есть, пропуск"
        else:
            write_orders(path, rows, seed)
            note = f"сгенерирован за {time.perf_counter() - t0:.1f} с"
        meta = pq.ParquetFile(path).metadata
        print(f"{path}: {meta.num_rows:,} строк, {meta.num_row_groups} row groups, "
              f"{path.stat().st_size / 2**20:.0f} МБ на диске ({note})")
    print("схема фактов:", ", ".join(f"{f.name}:{f.type}" for f in pq.read_schema(DATA / "orders_small.parquet")))


if __name__ == "__main__":
    main()
