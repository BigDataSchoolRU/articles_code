# duckdb==1.5.5, psutil==7.1.3 | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; настройки по duckdb.org/docs/current/guides/performance/oom и duckdb.org/2024/07/09/memory-management
"""DuckDB out-of-core: сортировка 30 млн строк при разном memory_limit и граничный случай с лимитом temp-каталога.

Каждый случай в отдельном процессе. Родитель меряет пиковый RSS и пиковый размер data/duckdb_tmp:
чем меньше memory_limit, тем больше DuckDB сбрасывает на диск. При max_temp_directory_size
меньше нужного объёма сброса запрос падает: так выглядит зависимость от свободного места.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import duckdb
import psutil

SRC = "data/orders_large.parquet"
OUT = "results/duckdb_sorted_large.parquet"
TMP = Path("data/duckdb_tmp")
COMMON = {"threads": "2", "preserve_insertion_order": "false", "temp_directory": f"'{TMP.as_posix()}'"}
CASES = {
    "sort_mem_1200mb": {"memory_limit": "'1200MB'"},
    "sort_mem_400mb": {"memory_limit": "'400MB'"},
    "sort_mem_400mb_tmp_64mb": {"memory_limit": "'400MB'", "max_temp_directory_size": "'64MB'"},
}
# Сортировка блокирующая: ей нужны все строки сразу, поэтому она и сбрасывает данные на диск
SORT_SQL = f"""
COPY (
    SELECT order_id, customer_id, product_id, ts, qty, price, discount, status
    FROM read_parquet('{SRC}')
    ORDER BY customer_id, ts
) TO '{OUT}' (FORMAT parquet)"""
TIMEOUT_S = 1200


def scrub(text: str) -> str:
    text = text.replace(sys.executable, "<python>")
    text = text.replace(str(Path.cwd()) + os.sep, "")
    text = re.sub(r"(/home|/root|/Users)/[^\s'\"]+", "<path>", text)
    text = re.sub(r"/usr(/local)?/bin/python[\d.]*", "<python>", text)
    text = re.sub(r"(?i)\bpid\b[\s:=]*\d+", "pid=<n>", text)
    return text


def child(name: str) -> None:
    con = duckdb.connect()
    for key, value in {**COMMON, **CASES[name]}.items():
        con.execute(f"SET {key} = {value}")
    t0 = time.perf_counter()
    result = {"case": name}
    try:
        con.execute(SORT_SQL)
        result["rows"] = con.execute(f"SELECT count(*) FROM read_parquet('{OUT}')").fetchone()[0]
        result["error"] = None
    except duckdb.Error as exc:
        result["rows"] = None
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - t0, 3)
    result["memory_limit"] = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    con.close()
    print("RESULT " + json.dumps(result, ensure_ascii=False))


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


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


def run_case(name: str):
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    proc = psutil.Popen([sys.executable, "06_duckdb_spill.py", "child", name],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    peak_rss, peak_tmp, t0 = 0, 0, time.perf_counter()
    while proc.poll() is None:
        peak_rss = max(peak_rss, tree_rss(proc))
        peak_tmp = max(peak_tmp, dir_size(TMP))
        if time.perf_counter() - t0 > TIMEOUT_S:
            proc.kill()
            break
        time.sleep(0.1)
    output = proc.communicate()[0] or ""
    result = None
    for line in output.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[len("RESULT "):])
    return result, peak_rss / 2**20, peak_tmp / 2**20, output


def main() -> None:
    if not Path(SRC).exists():
        raise SystemExit(f"нет {SRC}: сначала запустите 01_gen_data.py")
    Path("results").mkdir(exist_ok=True)
    print(f"duckdb {duckdb.__version__}, источник {SRC}, temp_directory {TMP.as_posix()}")
    print(f"{'случай':26} {'status':8} {'время, с':>9} {'пик RSS, МБ':>12} {'пик temp, МБ':>13}")
    unexpected = False
    for name in CASES:
        result, rss, tmp, output = run_case(name)
        if result is None:
            unexpected = True
            print(f"{name:26} {'crash':8} {'-':>9} {rss:12.0f} {tmp:13.0f}")
            print(scrub(output[-3000:]))
            continue
        status = "ok" if result["error"] is None else "error"
        print(f"{name:26} {status:8} {result['seconds']:9.2f} {rss:12.0f} {tmp:13.0f}", flush=True)
        if result["error"]:
            expected = "tmp_64mb" in name
            unexpected = unexpected or not expected
            print(f"  {'ожидаемо' if expected else 'НЕОЖИДАННО'}: {scrub(result['error'])}")
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"отсортированный результат: {OUT}")
    sys.exit(1 if unexpected else 0)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "child":
        child(sys.argv[2])
    else:
        main()
