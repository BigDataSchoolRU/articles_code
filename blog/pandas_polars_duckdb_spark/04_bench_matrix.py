# psutil==7.1.3 + движки из requirements.txt | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; методика по мотивам habr.com/ru/articles/1087386
"""Матрица прогона: 7 вариантов движков x 2 размера данных под общим бюджетом памяти 2 ГБ и 2 ядра.

Каждый запуск идёт отдельным процессом 03_engine_task.py. Сторож раз в 50 мс суммирует RSS
всего дерева процессов (для PySpark это Python-драйвер плюс JVM) и убивает дерево при
превышении бюджета. Это эмуляция docker run --memory=2g: cgroup тоже убивает, а не тормозит.
Ограничения замера: общая память процессов считается дважды, пик короче 50 мс можно пропустить.
Без Java варианты spark_* помечаются как skip и в сверку не идут.
"""
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import psutil

ENGINES = ["pandas", "polars_eager", "polars_lazy", "polars_streaming", "duckdb", "spark_default", "spark_tuned"]
# small: медиана трёх повторов, как у автора первоисточника; large: один прогон
SIZES = {"small": 3, "large": 1}
BUDGET_MB = 2048
TIMEOUT_S = 1200
LOGS = Path("results/logs")


def java_available() -> bool:
    home = os.environ.get("JAVA_HOME")
    if home and Path(home, "bin", "java").exists():
        return True
    return shutil.which("java") is not None


def scrub(text: str) -> str:
    # Убираем абсолютные пути, путь интерпретатора и PID из чужих сообщений об ошибках
    text = text.replace(sys.executable, "<python>")
    text = text.replace(str(Path.cwd()) + os.sep, "")
    text = re.sub(r"(/home|/root|/Users)/[^\s'\"]+", "<path>", text)
    text = re.sub(r"/usr(/local)?/bin/python[\d.]*", "<python>", text)
    text = re.sub(r"(?i)\bpid\b[\s:=]*\d+", "pid=<n>", text)
    return text


def tree_rss(proc: psutil.Process) -> int:
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


def kill_tree(proc: psutil.Process) -> None:
    try:
        kids = proc.children(recursive=True)
    except psutil.NoSuchProcess:
        kids = []
    for p in kids + [proc]:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def run_once(engine: str, size: str, i: int):
    log_path = LOGS / f"{engine}_{size}_{i}.log"
    env = dict(os.environ, POLARS_MAX_THREADS="2", SPARK_LOCAL_IP="127.0.0.1", PYTHONUNBUFFERED="1")
    peak, status = 0, "ok"
    t0 = time.perf_counter()
    with open(log_path, "w") as log:
        proc = psutil.Popen([sys.executable, "03_engine_task.py", engine, size],
                            stdout=log, stderr=subprocess.STDOUT, env=env)
        while proc.poll() is None:
            rss = tree_rss(proc)
            peak = max(peak, rss)
            if rss > BUDGET_MB * 2**20:
                status = f"OOM>{BUDGET_MB}MB"
                kill_tree(proc)
                break
            if time.perf_counter() - t0 > TIMEOUT_S:
                status = "timeout"
                kill_tree(proc)
                break
            time.sleep(0.05)
        proc.wait()
    text = log_path.read_text(errors="replace")
    result = None
    for line in text.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[len("RESULT "):])
    if status == "ok" and (proc.returncode != 0 or result is None):
        status = f"error rc={proc.returncode}"
    return status, peak / 2**20, result, text


def main() -> None:
    for src in ("data/orders_small.parquet", "data/orders_large.parquet", "data/products.parquet"):
        if not Path(src).exists():
            raise SystemExit(f"нет {src}: сначала запустите 01_gen_data.py")
    LOGS.mkdir(parents=True, exist_ok=True)
    has_java = java_available()
    print(f"бюджет памяти {BUDGET_MB} МБ на дерево процессов, 2 ядра, таймаут {TIMEOUT_S} с")
    if not has_java:
        print("java не найдена (ни JAVA_HOME, ни PATH): варианты spark_* пропускаются со статусом skip")
    rows = []
    for size, repeats in SIZES.items():
        for engine in ENGINES:
            if engine.startswith("spark") and not has_java:
                # Не запускаем заведомо падающий JVM-процесс, честно отмечаем пропуск
                rows.append({"engine": engine, "size": size, "status": "skip: no java",
                             "wall_s": None, "task_s": None, "peak_rss_mb": 0,
                             "groups": None, "n_orders": None, "revenue": None})
                print(f"пропуск {engine}/{size}: нет java", flush=True)
                continue
            walls, tasks, peak, status, result = [], [], 0.0, "ok", None
            for i in range(repeats):
                st, pk, res, text = run_once(engine, size, i)
                peak = max(peak, pk)
                if st != "ok":
                    status = st
                    print(f"{engine}/{size}: {st}, хвост лога results/logs/{engine}_{size}_{i}.log:")
                    print(scrub(text[-3000:]))
                    break
                result = res
                walls.append(res["wall_s"])
                tasks.append(res["task_s"])
            row = {"engine": engine, "size": size, "status": status,
                   "wall_s": round(statistics.median(walls), 2) if status == "ok" else None,
                   "task_s": round(statistics.median(tasks), 2) if status == "ok" else None,
                   "peak_rss_mb": round(peak),
                   "groups": result["groups"] if status == "ok" else None,
                   "n_orders": result["n_orders"] if status == "ok" else None,
                   "revenue": result["revenue"] if status == "ok" else None}
            rows.append(row)
            print(f"готово {engine}/{size}: {status}, task {row['task_s']} с, пик {row['peak_rss_mb']} МБ", flush=True)

    print()
    print(f"{'engine':18} {'size':6} {'status':14} {'wall, с':>8} {'task, с':>8} {'пик RSS, МБ':>12} {'заказов':>12}")
    for r in rows:
        wall = f"{r['wall_s']:.2f}" if r["wall_s"] is not None else "-"
        task = f"{r['task_s']:.2f}" if r["task_s"] is not None else "-"
        orders = f"{r['n_orders']:,}" if r["n_orders"] is not None else "-"
        print(f"{r['engine']:18} {r['size']:6} {r['status']:14} {wall:>8} {task:>8} {r['peak_rss_mb']:>12} {orders:>12}")
    print("wall включает старт SparkSession, task без него; у остальных движков они равны")

    # Сверяем, что все движки посчитали одно и то же
    for size in SIZES:
        ok = [r for r in rows if r["size"] == size and r["status"] == "ok"]
        if not ok:
            continue
        ref = ok[0]
        bad = [r["engine"] for r in ok
               if r["n_orders"] != ref["n_orders"] or abs(r["revenue"] - ref["revenue"]) > 1e-6 * abs(ref["revenue"])]
        print(f"сверка результатов {size}: " + ("совпадают у всех успешных" if not bad else f"РАСХОДЯТСЯ: {bad}"))

    out = Path("results/bench.csv")
    with open(out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"таблица сохранена в {out}")


if __name__ == "__main__":
    main()
