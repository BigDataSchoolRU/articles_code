# duckdb==2.0.0 | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 6. Граница встраиваемой модели: конкурентный доступ к файлу .duckdb.

1. Процесс A держит файл на запись, процесс B пытается открыть его на запись.
2. Процесс A держит файл на запись, процесс B пытается открыть его read_only.
3. Один процесс, несколько потоков с отдельными cursor() пишут в одну базу.
Текст ошибок урезаем: в нём есть абсолютный путь и PID.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import duckdb

DB = "data/lock_demo.duckdb"


def short_err(e: Exception) -> str:
    # Класс исключения и фраза до первого пути или PID
    msg = str(e).splitlines()[0]
    cut = len(msg)
    for marker in (' "', " '", "/", "\\", "(PID", "PID "):
        pos = msg.find(marker)
        if pos != -1:
            cut = min(cut, pos)
    return f"{type(e).__name__}: {msg[:cut].rstrip(' :')}"


def count_rows(con: duckdb.DuckDBPyConnection) -> int:
    # В DuckDB 2.0 у relation нет fetchone(): берём первую строку из fetchall()
    return con.sql("SELECT count(*) FROM t").fetchall()[0][0]


def hold_writer() -> None:
    # Дочерний процесс A: открывает файл на запись и держит подключение
    con = duckdb.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER, src VARCHAR)")
    con.execute("INSERT INTO t VALUES (0, 'A')")
    print("READY", flush=True)
    time.sleep(120)


def try_open(read_only: bool) -> None:
    try:
        con = duckdb.connect(DB, read_only=read_only)
        n = count_rows(con)
        print(f"    B открыл файл, строк в t = {n}")
        con.close()
    except Exception as e:  # noqa: BLE001
        print(f"    B получил ошибку: {short_err(e)}")


def main() -> None:
    Path("data").mkdir(exist_ok=True)
    for suffix in ("", ".wal"):
        Path(DB + suffix).unlink(missing_ok=True)

    # Процесс A запускаем тем же интерпретатором
    holder = subprocess.Popen(
        [sys.executable, __file__, "--hold"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        if line != "READY":
            print("Процесс A не стартовал")
            raise SystemExit(1)
        print(">>> 1. A держит файл на запись, B открывает на запись")
        try_open(read_only=False)
        print(">>> 2. A держит файл на запись, B открывает read_only")
        try_open(read_only=True)
    finally:
        holder.terminate()
        holder.wait(timeout=30)

    # Внутри одного процесса конкурентная запись работает: MVCC и оптимистичные транзакции
    con = duckdb.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER, src VARCHAR)")
    con.execute("DELETE FROM t")
    con.execute("INSERT INTO t VALUES (1, 'main'), (2, 'main'), (3, 'main')")
    workers, per_worker = 4, 200
    errors: list[str] = []

    def writer(k: int) -> None:
        cur = con.cursor()  # у каждого потока своё подключение к той же базе
        try:
            for j in range(per_worker):
                cur.execute("INSERT INTO t VALUES (?, ?)", [1000 * (k + 1) + j, f"w{k}"])
        except Exception as e:  # noqa: BLE001
            errors.append(short_err(e))
        finally:
            cur.close()

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    n = count_rows(con)
    expected = 3 + workers * per_worker
    print(f">>> 3. Один процесс, {workers} потока с отдельными cursor: строк в t = {n} (ожидалось {expected})")
    if errors:
        print(f"    ошибок в потоках: {len(errors)}, первая: {errors[0]}")
    con.close()
    if n != expected:
        raise SystemExit(1)


if __name__ == "__main__":
    if "--hold" in sys.argv:
        hold_writer()
    else:
        main()
