# duckdb 2.0.0 + ducklake (формат 1.1), каталог в SQLite, SeaweedFS 4.48 как S3, прогнано на стенде 2026-10-22
"""Те же события в DuckLake: метаданные в SQLite, данные Parquet в s3://lake/ducklake/.

Запуск: python ducklake_catalog.py
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import boto3
import duckdb

SECRET = """
    CREATE SECRET s3 (TYPE s3, KEY_ID 'admin', SECRET 'password123',
        ENDPOINT '127.0.0.1:8333', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')
"""
META = Path("work/lake.sqlite")
ATTACH = f"ATTACH 'ducklake:sqlite:{META}' AS dl (DATA_PATH 's3://lake/ducklake/')"
RAW = "read_parquet('s3://lake/raw/events/dt={day}/*.parquet', hive_partitioning = true, union_by_name = true)"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(SECRET)
    con.execute(ATTACH)
    return con


def writer(name: str) -> None:
    """Один из двух процессов, которые пишут в одну таблицу одновременно."""
    con = connect()
    ok = failed = 0
    for n in range(20):
        try:
            con.execute(f"INSERT INTO dl.events (event_id, dt, country, amount) VALUES ({n}, DATE '2026-10-13', '{name}', 1)")
            ok += 1
        except duckdb.Error as e:
            failed += 1
            last = str(e).splitlines()[0][:160]
    print(f"  писатель {name}: успешно {ok}, ошибок {failed}" + (f", последняя: {last}" if failed else ""))


def main() -> None:
    # чистый старт: локальная база метаданных и префикс данных в S3
    META.parent.mkdir(exist_ok=True)
    META.unlink(missing_ok=True)
    s3 = boto3.resource("s3", endpoint_url="http://127.0.0.1:8333", region_name="us-east-1",
                        aws_access_key_id="admin", aws_secret_access_key="password123")
    s3.Bucket("lake").objects.filter(Prefix="ducklake/").delete()

    con = connect()
    # первые десять дней одной транзакцией: это снапшот с таблицей
    con.execute("""
        CREATE TABLE dl.events AS
        SELECT event_id, user_id, country, amount, dt
        FROM read_parquet('s3://lake/raw/events/*/*.parquet', hive_partitioning = true, union_by_name = true)
        WHERE dt <= DATE '2026-10-10'
    """)
    con.execute(f"INSERT INTO dl.events SELECT event_id, user_id, country, amount, dt FROM {RAW.format(day='2026-10-11')}")

    # эволюция схемы: колонка добавляется в метаданные, старые файлы не переписываются
    con.execute("ALTER TABLE dl.events ADD COLUMN channel VARCHAR")
    con.execute(f"INSERT INTO dl.events SELECT event_id, user_id, country, amount, dt, channel FROM {RAW.format(day='2026-10-12')}")
    con.execute("DELETE FROM dl.events WHERE dt = DATE '2026-10-01' AND country = 'DE'")

    print("снапшоты:")
    for sid, changes in con.sql("SELECT snapshot_id, changes FROM ducklake_snapshots('dl') ORDER BY 1").fetchall():
        print(f"  {sid}: {changes}")

    print("строк сейчас:", con.sql("SELECT count(*) FROM dl.events").fetchall()[0][0])
    # time travel: та же таблица на момент любого снапшота
    for v in (1, 2, 3):
        print(f"строк AT (VERSION => {v}):", con.sql(f"SELECT count(*) FROM dl.events AT (VERSION => {v})").fetchall()[0][0])
    print("channel по дням:", con.sql(
        "SELECT dt, count(channel) FROM dl.events WHERE dt >= DATE '2026-10-11' GROUP BY dt ORDER BY dt").fetchall())

    files = con.sql("SELECT count(*), sum(data_file_size_bytes), count(delete_file) FROM ducklake_list_files('dl', 'events')").fetchall()[0]
    codec = con.sql("SELECT DISTINCT compression FROM parquet_metadata('s3://lake/ducklake/**/*.parquet')").fetchall()
    print("кодек Parquet по умолчанию:", codec)
    print(f"файлы данных: {files[0]}, {files[1] / 1024 / 1024:.1f} МБ, файлов удалений: {files[2]}")
    con.close()

    # что лежит в каталожной базе: обычные таблицы SQLite
    db = sqlite3.connect(META)
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY 1")]
    inlined = [t for t in tables if t.startswith("ducklake_inlined_data_")]
    print(f"{META}: {META.stat().st_size / 1024:.0f} КБ, таблиц {len(tables)}, из них со вставками в каталоге: {inlined}")
    db.close()

    # два процесса пишут в одну таблицу через один файл SQLite
    print("конкурентная запись, 2 процесса по 20 INSERT:")
    procs = [subprocess.Popen([sys.executable, "-u", __file__, "writer", n]) for n in ("A", "B")]
    for p in procs:
        p.wait()
    con = connect()
    print("  строк от писателей:", con.sql(
        "SELECT country, count(*) FROM dl.events WHERE dt = DATE '2026-10-13' GROUP BY 1 ORDER BY 1").fetchall())


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "writer":
        writer(sys.argv[2])
    else:
        main()
