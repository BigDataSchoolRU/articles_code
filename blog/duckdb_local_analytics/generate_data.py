# duckdb==2.0.0 | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 2. Синтетический набор заказов: генерация силами самого DuckDB, запись в Parquet и CSV.

Другие демо импортируют отсюда ensure_data() и пути к файлам.
"""
import argparse
import sys
import time
from pathlib import Path

import duckdb

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
PARQUET = DATA / "orders.parquet"
CSV = DATA / "orders.csv"
MARKER = DATA / "rows.txt"
DEFAULT_ROWS = 5_000_000

# Значения детерминированы через hash(i), поэтому набор одинаков при любом числе потоков
GEN_SQL = """
SELECT
    i AS order_id,
    TIMESTAMP '2026-01-01 00:00:00'
        + to_seconds(CAST(hash(i * 3) % 25920000 AS BIGINT)) AS ts,
    ['north', 'south', 'east', 'west', 'center'][1 + CAST(hash(i * 5) % 5 AS INTEGER)] AS region,
    'cat_' || CAST(hash(i * 7) % 50 AS VARCHAR) AS category,
    CAST(hash(i * 11) % 100000 AS DOUBLE) / 100 AS amount,
    1 + CAST(hash(i * 13) % 10 AS INTEGER) AS qty,
    CAST(hash(i * 17) % 200000 AS INTEGER) AS customer_id,
    md5(CAST(i AS VARCHAR)) AS note
FROM range({rows}) AS t(i)
"""


def q(path: Path) -> str:
    """Путь как строковый литерал SQL."""
    return str(path).replace("'", "''")


def mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def build(rows: int) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    t0 = time.perf_counter()
    con.execute(f"CREATE TABLE orders AS {GEN_SQL.format(rows=int(rows))}")
    print(f"Сгенерировано строк: {rows:,} за {time.perf_counter() - t0:.2f} с")

    # Parquet: колоночный формат, zstd, группы строк по 122 880 строк (min/max статистика на группу)
    t0 = time.perf_counter()
    con.execute(
        f"COPY orders TO '{q(PARQUET)}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 122880)"
    )
    print(f"Parquet записан за {time.perf_counter() - t0:.2f} с")

    # CSV: тот же набор построчным текстом, для сравнения размера и скорости чтения
    t0 = time.perf_counter()
    con.execute(f"COPY orders TO '{q(CSV)}' (FORMAT csv, HEADER true)")
    print(f"CSV записан за {time.perf_counter() - t0:.2f} с")

    MARKER.write_text(str(rows), encoding="utf-8")
    print(f"{PARQUET.name}: {mb(PARQUET):8.1f} MB")
    print(f"{CSV.name}:     {mb(CSV):8.1f} MB")
    print(f"CSV больше Parquet в {mb(CSV) / mb(PARQUET):.1f} раза")

    print("Первые строки набора:")
    print(con.sql("SELECT * FROM orders ORDER BY order_id LIMIT 3").df().to_string(index=False))
    con.close()


def ensure_data(rows: int = DEFAULT_ROWS) -> None:
    """Создаёт набор, если его нет или он другого размера."""
    ok = PARQUET.exists() and CSV.exists() and MARKER.exists()
    if ok and MARKER.read_text(encoding="utf-8").strip() == str(rows):
        return
    print("Набор данных не найден, генерирую...")
    build(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Генерация синтетических заказов в Parquet и CSV")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    args = parser.parse_args()
    build(args.rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
