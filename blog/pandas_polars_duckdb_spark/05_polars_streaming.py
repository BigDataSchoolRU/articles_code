# polars==1.44.2, psutil==7.1.3 | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; поведение движков по docs.pola.rs/user-guide/concepts/streaming
"""Polars на large (30 млн строк): eager против lazy, движок в памяти против streaming.

Каждый режим в отдельном процессе, сторож меряет пиковый RSS и убивает при превышении 2 ГБ.
В Polars 1.x collect() по умолчанию идёт в движке в памяти; в 2.0 engine='auto' выбирает streaming.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)
os.environ.setdefault("POLARS_MAX_THREADS", "2")

import polars as pl
import psutil

SRC = "data/orders_large.parquet"
OUT = "results/polars_sink_large.parquet"
MODES = ["eager_all_columns", "lazy_in_memory", "lazy_streaming", "sink_parquet_streaming"]
BUDGET_MB = 2048
TIMEOUT_S = 900


def scrub(text: str) -> str:
    text = text.replace(sys.executable, "<python>")
    text = text.replace(str(Path.cwd()) + os.sep, "")
    text = re.sub(r"(/home|/root|/Users)/[^\s'\"]+", "<path>", text)
    text = re.sub(r"/usr(/local)?/bin/python[\d.]*", "<python>", text)
    text = re.sub(r"(?i)\bpid\b[\s:=]*\d+", "pid=<n>", text)
    return text


def query(frame):
    # Группировка на 20 тыс. ключей; нужны 4 колонки из 9
    return (frame.filter(pl.col("status") != "CANCELLED")
                 .group_by("product_id")
                 .agg(pl.len().alias("n"),
                      (pl.col("qty") * pl.col("price")).sum().alias("revenue"),
                      pl.col("qty").mean().alias("avg_qty"))
                 .sort("product_id"))


def child(mode: str) -> None:
    t0 = time.perf_counter()
    if mode == "eager_all_columns":
        # Eager без columns=: в память едут все 9 колонок, включая строковую comment
        rows = query(pl.read_parquet(SRC)).height
    elif mode == "lazy_in_memory":
        # Lazy: projection pushdown читает 4 колонки, но всё выполняется в памяти
        rows = query(pl.scan_parquet(SRC)).collect().height
    elif mode == "lazy_streaming":
        rows = query(pl.scan_parquet(SRC)).collect(engine="streaming").height
    else:
        # Результат пишется на диск, не собираясь в DataFrame
        query(pl.scan_parquet(SRC)).sink_parquet(OUT)
        rows = pl.scan_parquet(OUT).select(pl.len()).collect().item()
    print("RESULT " + json.dumps({"mode": mode, "seconds": round(time.perf_counter() - t0, 3), "rows": rows}))


def tree_rss(proc) -> int:
    try:
        procs = [proc] + proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return 0
    total = 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def run_mode(mode: str):
    proc = psutil.Popen([sys.executable, "05_polars_streaming.py", "child", mode],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                        env=dict(os.environ, POLARS_MAX_THREADS="2"))
    peak, status, t0 = 0, "ok", time.perf_counter()
    while proc.poll() is None:
        rss = tree_rss(proc)
        peak = max(peak, rss)
        if rss > BUDGET_MB * 2**20 or time.perf_counter() - t0 > TIMEOUT_S:
            status = f"OOM>{BUDGET_MB}MB" if rss > BUDGET_MB * 2**20 else "timeout"
            proc.kill()
            break
        time.sleep(0.05)
    output = proc.communicate()[0] or ""
    result = None
    for line in output.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[len("RESULT "):])
    if status == "ok" and result is None:
        status = f"error rc={proc.returncode}"
    return status, peak / 2**20, result, output


def main() -> None:
    if not Path(SRC).exists():
        raise SystemExit(f"нет {SRC}: сначала запустите 01_gen_data.py")
    Path("results").mkdir(exist_ok=True)
    print(f"polars {pl.__version__}, источник {SRC}, бюджет {BUDGET_MB} МБ")
    print("оптимизированный lazy-план (видно, сколько колонок читается из Parquet):")
    print(query(pl.scan_parquet(SRC)).explain())
    print()
    print(f"{'режим':26} {'status':12} {'время, с':>9} {'пик RSS, МБ':>12} {'строк':>8}")
    for mode in MODES:
        status, peak, result, output = run_mode(mode)
        sec = f"{result['seconds']:.2f}" if result else "-"
        rows = result["rows"] if result else "-"
        print(f"{mode:26} {status:12} {sec:>9} {peak:12.0f} {rows:>8}", flush=True)
        if status != "ok":
            print(scrub(output[-3000:]))
    print(f"результат sink_parquet: {OUT}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "child":
        child(sys.argv[2])
    else:
        main()
