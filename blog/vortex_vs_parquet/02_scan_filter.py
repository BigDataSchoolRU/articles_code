# vortex-data==0.93.0 pylance==14.0.3 pyarrow==21.0.0 numpy==2.3.4; авторский демо-код, синтетические данные генерируются в скрипте
"""Сценарий 2: полный скан в Arrow и скан с фильтром по числовой и строковой колонке. Медиана из 5 повторов после прогрева."""
import os, re, statistics, sys, time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

os.chdir(Path(__file__).resolve().parent)
ROWS = 5_000_000
REPEATS = 5
DATA = Path("data")
CITY = "city_0007"
AMOUNT = 900.0


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
    # файлы создаёт 01_write_size.py; если их нет, пишем сами
    DATA.mkdir(exist_ok=True)
    paths = {k: DATA / v for k, v in {"parquet": "orders.parquet", "vortex": "orders.vortex",
                                     "lance": "orders.lance", "arrow_ipc": "orders.arrow"}.items()}
    if all(p.exists() for p in paths.values()):
        return paths
    import vortex as vx, lance
    t = make_table()
    pq.write_table(t, paths["parquet"], compression="zstd", use_dictionary=True)
    try:
        vx.io.write(t, str(paths["vortex"]))
    except TypeError:
        vx.io.write(vx.array(t), str(paths["vortex"]))
    lance.write_dataset(t, str(paths["lance"]), mode="overwrite")
    with pa.OSFile(str(paths["arrow_ipc"]), "wb") as s, pa.ipc.new_file(s, t.schema) as w:
        w.write_table(t)
    return paths


def vx_to_arrow(res):
    # результат скана Vortex приводим к pyarrow.Table, API менялся между версиями
    for attr in ("read_all",):
        if hasattr(res, attr):
            res = getattr(res, attr)()
    for attr in ("to_arrow_table", "to_arrow", "to_arrow_array"):
        if hasattr(res, attr):
            out = getattr(res, attr)()
            if isinstance(out, pa.Table):
                return out
            if isinstance(out, pa.RecordBatchReader):
                return out.read_all()
            if isinstance(out, (pa.StructArray, pa.ChunkedArray)):
                return pa.Table.from_struct_array(out) if isinstance(out, pa.StructArray) else pa.table(out.combine_chunks().flatten(), names=[f.name for f in out.type])
    raise TypeError(f"не удалось привести {type(res).__name__} к Arrow")


def vx_filter_expr():
    import vortex as vx
    ve = getattr(vx, "expr")
    col = getattr(ve, "column", None) or getattr(ve, "col")
    return (col("amount") > AMOUNT) & (col("city") == CITY)


def readers(paths):
    import lance, vortex as vx
    flt = [("amount", ">", AMOUNT), ("city", "=", CITY)]
    lance_ds = lance.dataset(str(paths["lance"]))
    def ipc_all():
        return pa.ipc.open_file(pa.memory_map(str(paths["arrow_ipc"]))).read_all()
    def ipc_flt():
        t = ipc_all()
        return t.filter(pc.and_(pc.greater(t["amount"], AMOUNT), pc.equal(t["city"], CITY)))
    return {
        "parquet": (lambda: pq.read_table(paths["parquet"]), lambda: pq.read_table(paths["parquet"], filters=flt)),
        "vortex": (lambda: vx_to_arrow(vx.open(str(paths["vortex"])).scan()),
                   lambda: vx_to_arrow(vx.open(str(paths["vortex"])).scan(expr=vx_filter_expr()))),
        "lance": (lambda: lance_ds.to_table(), lambda: lance_ds.to_table(filter=f"amount > {AMOUNT} AND city = '{CITY}'")),
        "arrow_ipc": (ipc_all, ipc_flt),
    }


def bench(fn):
    out = fn()  # прогрев
    times = []
    for _ in range(REPEATS):
        s = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - s)
    return statistics.median(times), out.num_rows


def main():
    paths = ensure_files()
    errors = 0
    print(f"фильтр: amount > {AMOUNT} AND city = '{CITY}', повторов {REPEATS}, медиана")
    print(f"{'format':<10} {'full_scan_s':>11} {'rows':>9} {'filter_s':>9} {'rows':>7}")
    for name, (full, filt) in readers(paths).items():
        try:
            t1, n1 = bench(full)
            t2, n2 = bench(filt)
            print(f"{name:<10} {t1:>11.3f} {n1:>9} {t2:>9.4f} {n2:>7}")
        except Exception as e:
            errors += 1
            print(f"ОШИБКА {name}: {type(e).__name__}: {clean(e)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
