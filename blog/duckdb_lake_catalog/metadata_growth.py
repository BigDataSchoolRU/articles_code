# duckdb 2.0.0 + ducklake (формат 1.1, SQLite) + iceberg (REST fixture 1.10.1), SeaweedFS 4.48, прогнано на стенде 2026-10-22
"""50 мелких дозаписей по 1000 строк в DuckLake и Iceberg: что растёт и что чистит обслуживание.

Запуск: python metadata_growth.py
"""
import time
from pathlib import Path

import boto3
import duckdb

APPENDS, ROWS = 50, 1000
META = Path("work/growth.sqlite")
s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:8333", region_name="us-east-1",
                  aws_access_key_id="admin", aws_secret_access_key="password123")


def objects(prefix: str) -> list:
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket="lake", Prefix=prefix)
    return [o for page in pages for o in page.get("Contents", [])]


def report(label: str, con: duckdb.DuckDBPyConnection) -> None:
    dl = objects("ducklake_growth/")
    ice = objects("iceberg/demo/growth/")
    ice_meta = [o for o in ice if "/metadata/" in o["Key"]]
    ice_data = [o for o in ice if "/data/" in o["Key"]]
    dl_snaps = con.sql("SELECT count(*) FROM ducklake_snapshots('dl')").fetchall()[0][0]
    ice_snaps = con.sql("SELECT count(*) FROM iceberg_snapshots(ice.demo.growth)").fetchall()[0][0]
    print(f"--- {label}")
    print(f"  DuckLake: Parquet в S3 {len(dl)} файлов, {sum(o['Size'] for o in dl) / 1024:.0f} КБ; "
          f"SQLite {META.stat().st_size / 1024:.0f} КБ; снапшотов {dl_snaps}")
    print(f"  Iceberg:  data/ {len(ice_data)} файлов, {sum(o['Size'] for o in ice_data) / 1024:.0f} КБ; "
          f"metadata/ {len(ice_meta)} файлов, {sum(o['Size'] for o in ice_meta) / 1024:.0f} КБ; снапшотов {ice_snaps}")
    for table in ("dl.growth", "ice.demo.growth"):
        t = time.time()
        n = con.sql(f"SELECT count(*), sum(amount) FROM {table}").fetchall()[0][0]
        print(f"  {table}: {n} строк, полный скан {time.time() - t:.2f} с")


META.parent.mkdir(exist_ok=True)
META.unlink(missing_ok=True)
for o in objects("ducklake_growth/"):
    s3.delete_object(Bucket="lake", Key=o["Key"])

con = duckdb.connect()
con.execute("""
    CREATE SECRET s3 (TYPE s3, KEY_ID 'admin', SECRET 'password123',
        ENDPOINT '127.0.0.1:8333', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')
""")
con.execute(f"ATTACH 'ducklake:sqlite:{META}' AS dl (DATA_PATH 's3://lake/ducklake_growth/')")
con.execute("ATTACH 'warehouse' AS ice (TYPE iceberg, ENDPOINT 'http://127.0.0.1:8181', AUTHORIZATION_TYPE 'none')")
con.execute("CREATE SCHEMA IF NOT EXISTS ice.demo")
con.execute("DROP TABLE IF EXISTS ice.demo.growth")
# DROP в REST fixture не удаляет файлы: чистим префикс сами, иначе счёт пойдёт по прошлым прогонам
for o in objects("iceberg/demo/growth/"):
    s3.delete_object(Bucket="lake", Key=o["Key"])
schema = "(event_id BIGINT, user_id BIGINT, country VARCHAR, amount DOUBLE)"
con.execute(f"CREATE TABLE dl.growth {schema}")
# Iceberg по умолчанию пишет Parquet в ZSTD, DuckLake в SNAPPY: выравниваем, чтобы сравнивать метаданные, а не кодек
con.execute("CALL dl.set_option('parquet_compression', 'zstd')")
con.execute(f"CREATE TABLE ice.demo.growth {schema}")

batch = f"SELECT i, (hash(i) % 50000)::BIGINT, 'DE', (i % 1000) / 10 FROM range({{n}} * {ROWS}, ({{n}} + 1) * {ROWS}) t(i)"
for table in ("dl.growth", "ice.demo.growth"):
    t = time.time()
    # каждая дозапись это отдельная транзакция и отдельный снапшот
    for n in range(APPENDS):
        con.execute(f"INSERT INTO {table} {batch.format(n=n)}")
    print(f"{table}: {APPENDS} INSERT по {ROWS} строк за {time.time() - t:.1f} с")

report(f"после {APPENDS} дозаписей", con)

# обслуживание DuckLake: склеить мелкие файлы, забыть старые снапшоты, удалить ненужное
for sql in ("CALL ducklake_merge_adjacent_files('dl')",
            "CALL ducklake_expire_snapshots('dl', older_than => now())",
            "CALL ducklake_cleanup_old_files('dl', cleanup_all => true)"):
    try:
        con.execute(sql)
        print("ok:", sql)
    except duckdb.Error as e:
        print("ошибка:", sql, "->", str(e).splitlines()[0][:200])
# у Iceberg в DuckDB есть только перезапись файлов данных, снапшоты и старые файлы чистит движок с полным API
try:
    con.execute("CALL iceberg_rewrite_data_files(ice.demo.growth)")
    print("ok: iceberg_rewrite_data_files")
except duckdb.Error as e:
    print("ошибка: iceberg_rewrite_data_files ->", str(e).splitlines()[0][:200])

report("после обслуживания", con)
