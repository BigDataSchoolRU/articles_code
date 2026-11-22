# vortex-data==0.93.0 pylance==14.0.3 pyarrow==21.0.0 numpy==2.3.4; авторский демо-код, синтетические данные генерируются в скрипте
"""Сценарий 1: запись одной таблицы в Parquet, Vortex, Lance и Arrow IPC, медиана времени записи и размер на диске."""
import os, re, shutil, statistics, sys, time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

os.chdir(Path(__file__).resolve().parent)
ROWS = 5_000_000
REPEATS = 5
DATA = Path("data")


def clean(msg):
    # убираем из текста исключения абсолютные пути и PID, длину не режем
    msg = re.sub(r"(/home|/root|/usr|/tmp|/opt)/\S*", "<path>", str(msg))
    return re.sub(r"(?i)pid[ =:]*\d+", "pid <n>", msg)


def make_table(n=ROWS):
    # детерминированный датасет: числа, строки с повторами, время
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


def remove(p):
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def size_of(p):
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size


def w_parquet(t, p):
    pq.write_table(t, p, compression="zstd", use_dictionary=True)


def w_vortex(t, p):
    import vortex as vx
    # в разных версиях write принимает Arrow-таблицу или vortex-массив
    try:
        vx.io.write(t, str(p))
    except TypeError:
        vx.io.write(vx.array(t), str(p))


def w_lance(t, p):
    import lance
    lance.write_dataset(t, str(p), mode="overwrite")


def w_ipc(t, p):
    with pa.OSFile(str(p), "wb") as sink, pa.ipc.new_file(sink, t.schema) as w:
        w.write_table(t)


FORMATS = {"parquet": ("orders.parquet", w_parquet), "vortex": ("orders.vortex", w_vortex),
           "lance": ("orders.lance", w_lance), "arrow_ipc": ("orders.arrow", w_ipc)}


def main():
    DATA.mkdir(exist_ok=True)
    t = make_table()
    print(f"строк: {t.num_rows}, колонок: {t.num_columns}, в памяти Arrow: {t.nbytes / 2**20:.1f} MiB")
    errors = 0
    rows = []
    for name, (fname, writer) in FORMATS.items():
        p = DATA / fname
        try:
            remove(p)
            writer(t, p)  # прогрев, без замера
            times = []
            for _ in range(REPEATS):
                remove(p)  # удаление вне замера
                s = time.perf_counter()
                writer(t, p)
                times.append(time.perf_counter() - s)
            rows.append((name, str(p), statistics.median(times), size_of(p)))
        except Exception as e:
            errors += 1
            print(f"ОШИБКА {name}: {type(e).__name__}: {clean(e)}")
    base = next((r[3] for r in rows if r[0] == "parquet"), None)
    print(f"{'format':<10} {'path':<22} {'write_med_s':>11} {'size_MiB':>9} {'x_parquet':>9}")
    for name, p, tm, sz in rows:
        ratio = f"{sz / base:.2f}" if base else "-"
        print(f"{name:<10} {p:<22} {tm:>11.3f} {sz / 2**20:>9.1f} {ratio:>9}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
