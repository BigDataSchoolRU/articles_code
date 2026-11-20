# duckdb==2.0.0, sqlite3 из стандартной библиотеки Python | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 5. Один и тот же агрегат в DuckDB и SQLite на одной машине. Цифры относятся только к этому прогону."""
import math
import os
import sqlite3
import sys
import time
import traceback
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import DATA, PARQUET, ensure_data, q  # noqa: E402

SQLITE_DB = DATA / "orders.sqlite"
AGG_SQL = (
    "SELECT region, category, count(*) AS n, sum(amount * qty) AS revenue "
    "FROM {src} GROUP BY region, category"
)
RUNS = 3


def setting(con, name: str):
    """Значение настройки через duckdb_settings(); None, если прочитать не удалось."""
    try:
        row = con.execute("SELECT value FROM duckdb_settings() WHERE name = ?", [name]).fetchone()
        if row is not None:
            return str(row[0])
    except duckdb.Error as exc:
        print(f"duckdb_settings() не прочитан: {type(exc).__name__}: {exc}")
    return None


def best_of(fn, runs: int = RUNS):
    times, result = [], None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return min(times), result


def to_map(rows) -> dict:
    return {(r[0], r[1]): (int(r[2]), float(r[3])) for r in rows}


def same(a: dict, b: dict) -> bool:
    if a.keys() != b.keys():
        return False
    return all(a[k][0] == b[k][0] and math.isclose(a[k][1], b[k][1], rel_tol=1e-9) for k in a)


def main() -> int:
    ensure_data()
    src = f"read_parquet('{q(PARQUET)}')"
    print(f"duckdb {duckdb.__version__}, sqlite {sqlite3.sqlite_version}")

    dcon = duckdb.connect()
    raw = setting(dcon, "threads")
    try:
        threads = int(raw)
    except (TypeError, ValueError):
        threads = os.cpu_count() or 4
        print(f"threads из настроек не прочитан ({raw!r}), беру число ядер: {threads}")
    print(f"DuckDB threads по умолчанию: {threads}; SQLite выполняет запрос в одном потоке")

    # 1. DuckDB прямо по Parquet, без загрузки
    t_pq, res_pq = best_of(lambda: dcon.execute(AGG_SQL.format(src=src)).fetchall())

    # 2. DuckDB по таблице в памяти процесса
    t0 = time.perf_counter()
    dcon.execute(f"CREATE TABLE orders AS SELECT region, category, amount, qty FROM {src}")
    load_duck = time.perf_counter() - t0
    t_tbl, res_tbl = best_of(lambda: dcon.execute(AGG_SQL.format(src="orders")).fetchall())

    # 3. Тот же DuckDB в одном потоке: убираем вклад параллелизма
    dcon.execute("SET threads = 1")
    t_tbl1, _ = best_of(lambda: dcon.execute(AGG_SQL.format(src="orders")).fetchall())
    dcon.execute(f"SET threads = {threads}")

    # 4. SQLite: сначала загрузка строк в файл БД, потом тот же GROUP BY
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(SQLITE_DB) + suffix).unlink(missing_ok=True)
    scon = sqlite3.connect(SQLITE_DB)
    scon.execute("PRAGMA journal_mode = OFF")
    scon.execute("PRAGMA synchronous = OFF")
    scon.execute("CREATE TABLE orders (region TEXT, category TEXT, amount REAL, qty INTEGER)")
    t0 = time.perf_counter()
    cur = dcon.cursor()
    cur.execute(f"SELECT region, category, amount, qty FROM {src}")
    loaded = 0
    while True:
        batch = cur.fetchmany(200_000)
        if not batch:
            break
        scon.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", batch)
        loaded += len(batch)
    scon.commit()
    cur.close()
    load_sqlite = time.perf_counter() - t0
    t_sq, res_sq = best_of(lambda: scon.execute(AGG_SQL.format(src="orders")).fetchall())
    sqlite_mb = SQLITE_DB.stat().st_size / 1024 / 1024

    print(f"\nЗагружено в SQLite строк: {loaded:,}, файл {sqlite_mb:.1f} MB")
    print(f"\n{'вариант':<36}{'загрузка, с':>14}{'запрос, с (min из 3)':>24}")
    print(f"{'DuckDB, read_parquet по файлу':<36}{'-':>14}{t_pq:>24.4f}")
    print(f"{'DuckDB, таблица в памяти':<36}{load_duck:>14.2f}{t_tbl:>24.4f}")
    print(f"{'DuckDB, таблица, threads=1':<36}{'-':>14}{t_tbl1:>24.4f}")
    print(f"{'SQLite, таблица в файле':<36}{load_sqlite:>14.2f}{t_sq:>24.4f}")
    print(f"\nSQLite / DuckDB (таблица): {t_sq / t_tbl:.1f}x; SQLite / DuckDB (threads=1): {t_sq / t_tbl1:.1f}x")
    print("Это одна машина и один набор данных, обобщать на другие нагрузки нельзя")

    ok = same(to_map(res_pq), to_map(res_tbl)) and same(to_map(res_tbl), to_map(res_sq))
    print(f"Результаты трёх вариантов совпали: {ok} ({len(res_sq)} групп)")
    scon.close()
    dcon.close()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
