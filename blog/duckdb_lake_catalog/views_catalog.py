# duckdb 2.0.0, SeaweedFS 4.48 как S3, прогнано на стенде 2026-10-22
"""Каталог из одних представлений: файл DuckDB без данных, который лежит рядом с озером.

build  собрать catalog.duckdb из представлений и выложить в s3://lake/catalog/
read   подключить каталог READ_ONLY из чистого процесса, как это делает читатель
"""
import sys
import time
from pathlib import Path

import boto3
import duckdb

SECRET = """
    CREATE SECRET s3 (TYPE s3, KEY_ID 'admin', SECRET 'password123',
        ENDPOINT '127.0.0.1:8333', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')
"""
CATALOG_URL = "s3://lake/catalog/catalog.duckdb"
s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:8333", region_name="us-east-1",
                  aws_access_key_id="admin", aws_secret_access_key="password123")


def build() -> None:
    path = Path("work/catalog.duckdb")
    path.parent.mkdir(exist_ok=True)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    # секрет в файл каталога не попадает: каждый читатель заводит свой
    con.execute(SECRET)
    # в каталоге хранится только текст запроса; glob подхватит новые партиции сам
    con.execute("""
        CREATE VIEW events AS
        SELECT * FROM read_parquet('s3://lake/raw/events/*/*.parquet', hive_partitioning = true)
    """)
    con.execute("""
        CREATE VIEW daily AS
        SELECT dt, count(*) AS events, round(sum(amount), 2) AS revenue
        FROM events GROUP BY dt ORDER BY dt
    """)
    print("представления:", con.sql("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall())
    print("текст events:", con.sql("SELECT sql FROM duckdb_views() WHERE view_name = 'events'").fetchall()[0][0])
    con.close()

    s3.upload_file(str(path), "lake", "catalog/catalog.duckdb")
    data = sum(o["Size"] for o in s3.list_objects_v2(Bucket="lake", Prefix="raw/events/")["Contents"])
    print(f"catalog.duckdb: {path.stat().st_size / 1024:.0f} КБ, данные под ним: {data / 1024 / 1024:.1f} МБ")


def read() -> None:
    con = duckdb.connect()
    # без секрета читатель не доберётся ни до файла каталога, ни до данных
    try:
        con.execute(f"ATTACH '{CATALOG_URL}' AS cat (READ_ONLY)")
    except duckdb.Error as e:
        print("ATTACH без секрета:", type(e).__name__, str(e).splitlines()[0][:160])

    con.execute(SECRET)
    t = time.time()
    con.execute(f"ATTACH '{CATALOG_URL}' AS cat (READ_ONLY)")
    print(f"ATTACH READ_ONLY по s3: {time.time() - t:.2f} с")

    t = time.time()
    rows = con.sql("SELECT * FROM cat.daily").fetchall()
    print(f"cat.daily за {time.time() - t:.2f} с:")
    for dt, events, revenue in rows:
        print(f"  {dt}  {events:>7}  {revenue:>12}")

    print("колонки cat.events:", [c[0] for c in con.sql("DESCRIBE cat.events").fetchall()])
    try:
        print("channel по дням:", con.sql(
            "SELECT dt, count(channel) FROM cat.events GROUP BY dt ORDER BY dt DESC LIMIT 2").fetchall())
    except duckdb.Error as e:
        print("запрос к channel:", type(e).__name__, str(e).splitlines()[0][:200])

    # каталог только для чтения: правится пересборкой и перезаливкой файла
    try:
        con.execute("CREATE TABLE cat.scratch AS SELECT 1")
    except duckdb.Error as e:
        print("запись в каталог:", type(e).__name__, str(e).splitlines()[0][:160])


if __name__ == "__main__":
    {"build": build, "read": read}[sys.argv[1]]()
