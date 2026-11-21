# duckdb==2.0.0 | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 7. SET memory_limit и out-of-core: тяжёлая агрегация с лимитом памяти.

Каждый лимит прогоняется в отдельном процессе, чтобы честно снять пиковый RSS.
Пик spill считаем опросом каталога temp_directory во время запроса.
Ожидание: без лимита запрос идёт в памяти, с умеренным лимитом DuckDB
сбрасывает промежуточные данные на диск, со слишком малым падает с OOM.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

LIMITS = ["none", "256MB", "20MB"]
# Почти уникальная пара ключей: около 5 млн групп в хеш-агрегате
QUERY = """
SELECT count(*) AS groups, sum(rev) AS total
FROM (
    SELECT customer_id, product_id, sum(quantity * price) AS rev
    FROM read_parquet('data/orders.parquet')
    GROUP BY customer_id, product_id
)
"""


def short_err(e: Exception) -> str:
    msg = str(e).splitlines()[0]
    cut = len(msg)
    for marker in (' "', " '", "/", "\\", "(PID", "PID "):
        pos = msg.find(marker)
        if pos != -1:
            cut = min(cut, pos)
    return f"{type(e).__name__}: {msg[:cut].rstrip(' :')}"


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass  # файл spill успел удалиться
    return total


def peak_rss_mb() -> float:
    import resource
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux отдаёт килобайты, macOS байты
    return r / 1024 / 1024 if sys.platform == "darwin" else r / 1024


def run_one(limit: str) -> None:
    import duckdb

    spill = Path("data/spill") / limit
    shutil.rmtree(spill, ignore_errors=True)
    spill.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{spill.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")
    if limit != "none":
        con.execute(f"SET memory_limit = '{limit}'")

    peak = {"spill": 0}
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            peak["spill"] = max(peak["spill"], dir_size(spill))
            time.sleep(0.02)

    w = threading.Thread(target=watch, daemon=True)
    w.start()
    t0 = time.perf_counter()
    ok, err, res = True, "", None
    try:
        # В DuckDB 2.0 у relation нет fetchone(): берём первую строку из fetchall()
        res = con.sql(QUERY).fetchall()[0]
    except Exception as e:  # noqa: BLE001
        ok, err = False, short_err(e)
    elapsed = time.perf_counter() - t0
    stop.set()
    w.join()
    con.close()
    shutil.rmtree(spill, ignore_errors=True)
    print(json.dumps({
        "limit": limit, "ok": ok, "time": elapsed,
        "spill_mb": peak["spill"] / 1024 / 1024, "rss_mb": peak_rss_mb(),
        "groups": res[0] if res else None, "error": err,
    }, ensure_ascii=False))


def main() -> None:
    results = []
    for limit in LIMITS:
        # Отдельный процесс на каждый лимит, тем же интерпретатором
        proc = subprocess.run(
            [sys.executable, __file__, "--run", limit],
            capture_output=True, text=True, timeout=900,
        )
        line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith("{")), None)
        if line is None:
            results.append({"limit": limit, "ok": False, "time": 0.0, "spill_mb": 0.0,
                            "rss_mb": 0.0, "groups": None,
                            "error": f"процесс завершился с кодом {proc.returncode}"})
        else:
            results.append(json.loads(line))

    print(f"{'лимит':<8}{'успех':>7}{'время, с':>10}{'пик spill, MB':>15}{'пик RSS, MB':>13}")
    for r in results:
        print(f"{r['limit']:<8}{str(r['ok']):>7}{r['time']:>10.3f}{r['spill_mb']:>15.1f}{r['rss_mb']:>13.1f}")
    for r in results:
        if r["ok"]:
            print(f"{r['limit']}: групп в результате {r['groups']}")
        else:
            print(f"{r['limit']}: {r['error']}")

    # Ожидаемая картина: none и 256MB проходят, 20MB падает
    expected = {"none": True, "256MB": True}
    if any(r["ok"] != expected[r["limit"]] for r in results if r["limit"] in expected):
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--run":
        run_one(sys.argv[2])
    else:
        main()
