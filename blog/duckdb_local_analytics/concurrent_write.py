# duckdb==2.0.0 | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 6. Один файл .duckdb и несколько процессов: какая ошибка приходит второму писателю."""
import subprocess
import sys
import threading
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import DATA  # noqa: E402

DB = DATA / "lock_demo.duckdb"

# Код второго процесса: открыть файл на запись (rw) или только на чтение (ro)
CHILD = '''
import sys
import duckdb
path, mode = sys.argv[1], sys.argv[2]
try:
    con = duckdb.connect(path, read_only=(mode == "ro"))
    if mode == "rw":
        con.execute("INSERT INTO t VALUES (100)")
    n = con.execute("SELECT count(*) FROM t").fetchone()[0]
    print(f"OK mode={mode} rows={n}")
except Exception as exc:
    print(f"ERROR mode={mode} {type(exc).__name__}: {exc}")
    sys.exit(3)
'''

unexpected = []


def run_child(title: str, mode: str, expect_ok=None) -> None:
    p = subprocess.run(
        [sys.executable, "-c", CHILD, str(DB), mode],
        capture_output=True, text=True, timeout=120,
    )
    out = (p.stdout + p.stderr).strip()
    ok = p.returncode == 0
    if expect_ok is None:
        verdict = "для справки"
    elif ok == expect_ok:
        verdict = "как ожидалось"
    else:
        verdict = "НЕОЖИДАННО"
        unexpected.append(title)
    print(f"\n>>> {title}")
    print(f"    код выхода {p.returncode} [{verdict}]")
    print(f"    {out}")


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    for f in (DB, Path(str(DB) + ".wal")):
        f.unlink(missing_ok=True)

    # Процесс A открывает файл на запись и держит подключение
    holder = duckdb.connect(str(DB))
    holder.execute("CREATE TABLE t (x INTEGER)")
    holder.execute("INSERT INTO t VALUES (1), (2), (3)")

    run_child("1. A держит файл на запись, B открывает на запись", "rw", expect_ok=False)
    run_child("2. A держит файл на запись, B открывает read_only", "ro")

    # Внутри одного процесса писать из нескольких потоков можно: у каждого свой cursor
    def writer(k: int) -> None:
        cur = holder.cursor()
        for j in range(200):
            cur.execute("INSERT INTO t VALUES (?)", [k * 1000 + j])
        cur.close()

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    n = holder.execute("SELECT count(*) FROM t").fetchone()[0]
    print(f"\n>>> 3. Один процесс, 4 потока с отдельными cursor: строк в t = {n} (ожидалось 803)")
    if n != 803:
        unexpected.append("3. запись из потоков одного процесса")
    holder.close()

    # Процесс A открывает файл только на чтение: читателей может быть несколько
    reader = duckdb.connect(str(DB), read_only=True)
    run_child("4. A открыт read_only, B тоже read_only", "ro", expect_ok=True)
    run_child("5. A открыт read_only, B пытается писать", "rw", expect_ok=False)
    reader.close()

    run_child("6. Файл никто не держит, B открывает на запись", "rw", expect_ok=True)

    print("\nНеожиданные исходы:", ", ".join(unexpected) if unexpected else "нет")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
