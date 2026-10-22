# duckdb 2.0.0 + iceberg, apache/iceberg-rest-fixture 1.10.1, SeaweedFS 4.48 как S3, прогнано на стенде 2026-10-22
"""Те же события в Iceberg через REST-каталог: метаданные и данные в s3://lake/iceberg/.

Запуск: python iceberg_catalog.py
"""
import json
import urllib.request

import boto3
import duckdb

con = duckdb.connect()
con.execute("""
    CREATE SECRET s3 (TYPE s3, KEY_ID 'admin', SECRET 'password123',
        ENDPOINT '127.0.0.1:8333', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')
""")
# DuckDB пишет в Iceberg только через подключённый каталог
con.execute("ATTACH 'warehouse' AS ice (TYPE iceberg, ENDPOINT 'http://127.0.0.1:8181', AUTHORIZATION_TYPE 'none')")
con.execute("CREATE SCHEMA IF NOT EXISTS ice.demo")
con.execute("DROP TABLE IF EXISTS ice.demo.events")
s3 = boto3.resource("s3", endpoint_url="http://127.0.0.1:8333", region_name="us-east-1",
                    aws_access_key_id="admin", aws_secret_access_key="password123")
# DROP в REST fixture не удаляет файлы: чистим префикс сами, иначе счёт пойдёт по прошлым прогонам
s3.Bucket("lake").objects.filter(Prefix="iceberg/demo/events/").delete()

RAW = "read_parquet('s3://lake/raw/events/*/*.parquet', hive_partitioning = true, union_by_name = true)"
con.execute(f"""
    CREATE TABLE ice.demo.events AS
    SELECT event_id, user_id, country, amount, dt FROM {RAW} WHERE dt <= DATE '2026-10-10'
""")
con.execute(f"INSERT INTO ice.demo.events SELECT event_id, user_id, country, amount, dt FROM {RAW} WHERE dt = DATE '2026-10-11'")

try:
    con.execute("ALTER TABLE ice.demo.events ADD COLUMN channel VARCHAR")
    con.execute(f"INSERT INTO ice.demo.events SELECT event_id, user_id, country, amount, dt, channel FROM {RAW} WHERE dt = DATE '2026-10-12'")
    print("ADD COLUMN: да")
except duckdb.Error as e:
    print("ADD COLUMN:", type(e).__name__, str(e).splitlines()[0][:200])
    con.execute(f"INSERT INTO ice.demo.events SELECT event_id, user_id, country, amount, dt FROM {RAW} WHERE dt = DATE '2026-10-12'")
con.execute("DELETE FROM ice.demo.events WHERE dt = DATE '2026-10-01' AND country = 'DE'")

snaps = con.sql("""
    SELECT sequence_number, snapshot_id, operation,
           summary['added-records'], summary['total-records']
    FROM iceberg_snapshots(ice.demo.events) ORDER BY 1
""").fetchall()
print("снапшоты:")
for seq, sid, op, added, total in snaps:
    print(f"  {seq}: {op}, добавлено {added}, всего {total} (id {sid})")

print("строк сейчас:", con.sql("SELECT count(*) FROM ice.demo.events").fetchall()[0][0])
# time travel по id снапшота
first = snaps[0][1]
try:
    print("строк AT (VERSION => первый):", con.sql(f"SELECT count(*) FROM ice.demo.events AT (VERSION => {first})").fetchall()[0][0])
except duckdb.Error as e:
    print("time travel:", type(e).__name__, str(e).splitlines()[0][:200])

# REST-каталог отдаёт любому движку только указатель на текущий metadata.json
with urllib.request.urlopen("http://127.0.0.1:8181/v1/namespaces/demo/tables/events") as r:
    print("REST metadata-location:", json.load(r)["metadata-location"])

objs = list(s3.Bucket("lake").objects.filter(Prefix="iceberg/demo/events/"))
for kind in ("metadata", "data"):
    part = [o for o in objs if f"/events/{kind}/" in o.key]
    print(f"{kind}/: {len(part)} файлов, {sum(o.size for o in part) / 1024:.0f} КБ")
