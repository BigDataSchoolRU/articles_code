# duckdb==2.0.1 vortex-data==0.93.0 pyarrow==21.0.0 numpy==2.3.4; авторский демо-код, синтетические данные генерируются в скрипте
"""Сценарий 4: один SQL-запрос в DuckDB по Parquet и по Vortex через расширение vortex. Если расширение не ставится, демо падает с причиной."""
import os, re, statistics, sys, time
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

os.chdir(Path(__file__).resolve().parent)
ROWS = 5_000_000
REPEATS = 5
DATA = Path("data")
SQL = ("SELECT city, count(*) AS n, round(sum(amount), 2) AS revenue FROM {src} "
       "WHERE status = 'paid' AND amount > 500 GROUP BY city ORDER BY revenue DESC LIMIT 3")


def clean(msg):
    msg = re.sub(r"(/home|/root|/usr|/tmp|/opt)/\S*", "<path>", str(msg))
    return re.sub(r"(?i)pid[ =:]*\d+", "pid <n>", msg)


def make_table(n=ROWS):
    rng = np.random.default_rng(42)
    cities = pa.array([f"city_{i:04d}" for i in range(500)])
    city_codes = (rng.random(n) ** 3 * 500).astype(np.int32)
    statuses = pa.array(["new", "paid", "shipped", "done", "cancel"])
    st_codes = rng.integers(0, 5, n, dtype=np.int32)
    ts0 = np.datetime64("2026-01-01T00:00:00", "us").astype(np.int64)
    ts = ts0 + np.arange(n, dtype=np.int64) * 1_000_000 + rng.integers(0, 1_000_000, n)
    return pa.table({
        "id": pa.array(np.arange(n, dtype=np.int64)),
        "amount": pa.array(np.round(rng.gamma(2.0, 150.0, n), 2)),
        "qty": pa.array(rng.integers(1, 20, n, dtype=np.int32)),
        "city": pa.DictionaryArray.from_arrays(pa.array(city_codes), cities).dictionary_decode(),
        "status": pa.DictionaryArray.from_arrays(pa.array(st_codes), statuses).dictionary_decode(),
        "ts": pa.array(ts, pa.timestamp("us")),
    })


def ensure_files():
    DATA.mkdir(exist_ok=True)
    pqp, vxp = DATA / "orders.parquet", DATA / "orders.vortex"
    if pqp.exists() and vxp.exists():
        return pqp, vxp
    import vortex as vx
    t = make_table()
    pq.write_table(t, pqp, compression="zstd", use_dictionary=True)
    try:
        vx.io.write(t, str(vxp))
    except TypeError:
        vx.io.write(vx.array(t), str(vxp))
    return pqp, vxp


def bench(con, sql):
    res = con.execute(sql).fetchall()  # прогрев
    times = []
    for _ in range(REPEATS):
        s = time.perf_counter()
        res = con.execute(sql).fetchall()
        times.append(time.perf_counter() - s)
    return statistics.median(times), res


def main():
    pqp, vxp = ensure_files()
    con = duckdb.connect()
    print(f"duckdb {duckdb.__version__}")
    t, res = bench(con, SQL.format(src=f"read_parquet('{pqp.as_posix()}')"))
    print(f"parquet {pqp.as_posix()}: медиана {t:.3f} s, результат {res}")
    # расширение vortex ставится из репозитория расширений DuckDB
    try:
        con.execute("INSTALL vortex")
        con.execute("LOAD vortex")
    except Exception as e:
        print(f"ОГРАНИЧЕНИЕ: расширение vortex для duckdb {duckdb.__version__} не установилось: {type(e).__name__}: {clean(e)}")
        sys.exit(2)
    try:
        t2, res2 = bench(con, SQL.format(src=f"read_vortex('{vxp.as_posix()}')"))
    except Exception as e:
        print(f"ОШИБКА чтения {vxp.as_posix()} через DuckDB: {type(e).__name__}: {clean(e)}")
        sys.exit(1)
    print(f"vortex  {vxp.as_posix()}: медиана {t2:.3f} s, результат {res2}")
    print(f"результаты совпадают: {res == res2}, отношение parquet/vortex: {t / t2:.2f}")
    sys.exit(0 if res == res2 else 1)


if __name__ == "__main__":
    main()
