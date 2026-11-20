# duckdb==2.0.0 | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 7. SET memory_limit и out-of-core: тяжёлый GROUP BY без лимита, с лимитом 256MB и с заведомо малым лимитом.

Каждая конфигурация идёт в отдельном процессе, чтобы пик RSS не смешивался.
"""
import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import DATA, PARQUET, ensure_data, q  # noqa: E402

CONFIGS = ["none", "256MB", "20MB"]

# note уникален для каждой строки: хеш-таблица агрегата на 5 млн групп
QUERY = """
SELECT note, customer_id, round(sum(amount * qty), 2) AS revenue
FROM read_parquet('{src}')
GROUP BY note, customer_id
ORDER BY revenue DESC, note
LIMIT 5
"""


def setting(con, name: str) -> str:
    """Значение настройки через duckdb_settings(); текст ошибки, если прочитать не удалось."""
    try:
        row = con.execute("SELECT value FROM duckdb_settings() WHERE name = ?", [name]).fetchone()
        return str(row[0]) if row is not None else "<нет в duckdb_settings()>"
    except duckdb.Error as exc:
        return f"<не удалось прочитать: {type(exc).__name__}: {exc}>"


def dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def peak_rss_mb():
    try:
        import resource
    except ImportError:
        return None
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux отдаёт килобайты, macOS байты
    return r / 1024 / 1024 if sys.platform == "darwin" else r / 1024


def child(limit: str) -> int:
    spill = DATA / f"spill_{limit.lower()}"
    shutil.rmtree(spill, ignore_errors=True)
    spill.mkdir(parents=True)
    result = {"limit": limit}

    # Фоновый поток замеряет пиковый объём временных файлов во время запроса
    peak = [0]
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            peak[0] = max(peak[0], dir_size(spill))
            time.sleep(0.05)

    th = threading.Thread(target=poll, daemon=True)
    t0 = time.perf_counter()
    con = None
    try:
        con = duckdb.connect()
        con.execute("SET threads = 4")
        con.execute("SET preserve_insertion_order = false")
        # Каталог, куда DuckDB сбрасывает промежуточные данные при нехватке памяти
        con.execute(f"SET temp_directory = '{q(spill)}'")
        if limit != "none":
            con.execute(f"SET memory_limit = '{limit}'")
        print("memory_limit =", setting(con, "memory_limit"))

        th.start()
        t0 = time.perf_counter()
        rows = con.execute(QUERY.format(src=q(PARQUET))).fetchall()
        result.update(ok=True, rows=len(rows))
        for r in rows:
            print("   ", r)
    except duckdb.Error as exc:
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        print(f"ОШИБКА {type(exc).__name__}: {exc}")
    except Exception as exc:
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        stop.set()
        if th.is_alive():
            th.join()
    result["seconds"] = round(time.perf_counter() - t0, 3)
    result["peak_spill_mb"] = round(peak[0] / 1024 / 1024, 1)
    rss = peak_rss_mb()
    result["peak_rss_mb"] = round(rss, 1) if rss is not None else None
    if con is not None:
        con.close()
    shutil.rmtree(spill, ignore_errors=True)
    # Строку RESULT печатаем всегда, чтобы родитель видел исход и при ошибке
    print("RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    return 0


def parent() -> int:
    ensure_data()
    results = []
    for limit in CONFIGS:
        print(f"\n===== memory_limit: {limit} =====")
        try:
            p = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--child", limit],
                capture_output=True, text=True, timeout=1200,
            )
        except subprocess.TimeoutExpired:
            results.append({"limit": limit, "ok": False, "error": "таймаут 1200 с"})
            continue
        print(p.stdout.rstrip())
        if p.stderr.strip():
            print("stderr:", p.stderr.strip())
        found = [line for line in p.stdout.splitlines() if line.startswith("RESULT ")]
        if found:
            results.append(json.loads(found[-1][len("RESULT "):]))
        else:
            # Без RESULT процесс упал целиком, например убит OOM-киллером
            results.append({"limit": limit, "ok": False, "error": f"процесс завершился с кодом {p.returncode}"})

    print(f"\n{'лимит':<8}{'успех':>7}{'время, с':>10}{'пик spill, MB':>15}{'пик RSS, MB':>13}")
    for r in results:
        print(f"{r['limit']:<8}{str(r.get('ok')):>7}{str(r.get('seconds', '-')):>10}"
              f"{str(r.get('peak_spill_mb', '-')):>15}{str(r.get('peak_rss_mb', '-')):>13}")
        if not r.get("ok"):
            print(f"    ошибка: {r.get('error')}")

    baseline_ok = bool(results and results[0].get("ok"))
    return 0 if baseline_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", default=None, help="служебный режим: одна конфигурация")
    args = parser.parse_args()
    if args.child:
        return child(args.child)
    return parent()


if __name__ == "__main__":
    sys.exit(main())
