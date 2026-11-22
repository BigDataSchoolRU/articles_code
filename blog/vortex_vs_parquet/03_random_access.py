# vortex-data==0.93.0 pylance==14.0.3 pyarrow==21.0.0 numpy==2.3.4; авторский демо-код, синтетические данные генерируются в скрипте
"""Сценарий 3: выборка N случайных строк по индексу (точечное чтение). Граничный случай для Parquet: декодируются целые страницы."""
import os, re, statistics, sys, time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.dataset as pds
import pyarrow.parquet as pq

os.chdir(Path(__file__).resolve().parent)
ROWS = 5_000_000
REPEATS = 5
DATA = Path("data")
TAKE_SIZES = (10, 1000)


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


def vx_rows(res):
    if hasattr(res, "read_all"):
        res = res.read_all()
    for attr in ("to_arrow_table", "to_arrow", "to_arrow_array"):
        if hasattr(res, attr):
            out = getattr(res, attr)()
            if isinstance(out, pa.RecordBatchReader):
                out = out.read_all()
            return len(out)
    return len(res)


def vx_take(path, idx):
    import vortex as vx
    f = vx.open(str(path))
    # Vortex принимает отсортированные индексы строк прямо в scan
    return vx_rows(f.scan(indices=vx.array(pa.array(idx, pa.uint64()))))


def main():
    import lance
    paths = ensure_files()
    lance_ds = lance.dataset(str(paths["lance"]))
    pq_ds = pds.dataset(str(paths["parquet"]), format="parquet")
    rng = np.random.default_rng(7)
    meta = pq.ParquetFile(paths["parquet"]).metadata
    print(f"data/orders.parquet: row groups {meta.num_row_groups}, строк в первой {meta.row_group(0).num_rows}")
    takers = {
        "parquet": lambda idx: len(pq_ds.take(pa.array(idx))),
        "vortex": lambda idx: vx_take(paths["vortex"], idx),
        "lance": lambda idx: len(lance_ds.take(idx.tolist())),
        "arrow_ipc": lambda idx: len(pa.ipc.open_file(pa.memory_map(str(paths["arrow_ipc"]))).read_all().take(pa.array(idx))),
    }
    errors = 0
    print(f"{'format':<10} {'N':>6} {'take_med_ms':>12} {'rows':>6}")
    for n in TAKE_SIZES:
        idx_sets = [np.sort(rng.choice(ROWS, n, replace=False)) for _ in range(REPEATS + 1)]
        for name, fn in takers.items():
            try:
                fn(idx_sets[0])  # прогрев
                times = []
                for idx in idx_sets[1:]:
                    s = time.perf_counter()
                    got = fn(idx)
                    times.append(time.perf_counter() - s)
                print(f"{name:<10} {n:>6} {statistics.median(times) * 1000:>12.2f} {got:>6}")
            except Exception as e:
                errors += 1
                print(f"ОШИБКА {name} N={n}: {type(e).__name__}: {clean(e)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
