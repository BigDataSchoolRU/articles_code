# boto3 1.43.117, requests 2.34.2, iceberg-rest-fixture 1.10.1, прогнано на стенде 2026-10-22
"""Где лежит NDV: раздел statistics в metadata.json и футер Puffin-файла.

Запуск: python inspect_metadata.py [таблица]   (по умолчанию orders)
"""
import json
import struct
import sys

import boto3
import requests

REST = "http://127.0.0.1:8181/v1/namespaces/tpch/tables/"
table = sys.argv[1] if len(sys.argv) > 1 else "orders"

# REST-каталог отдаёт текущий metadata.json таблицы целиком
resp = requests.get(REST + table, timeout=30)
resp.raise_for_status()
meta = resp.json()["metadata"]
schema = {f["id"]: f["name"] for f in meta["schemas"][-1]["fields"]}
print("таблица", table, "текущий snapshot", meta["current-snapshot-id"])
print("снапшотов в истории", len(meta["snapshots"]))

stats = meta.get("statistics", [])
print("файлов в разделе statistics:", len(stats))
for sf in stats:
    print(" snapshot-id", sf["snapshot-id"], "файл", sf["statistics-path"].rsplit("/", 1)[-1])
    print(" размер", sf["file-size-in-bytes"], "байт, футер", sf["file-footer-size-in-bytes"], "байт")
    for b in sf["blob-metadata"]:
        cols = ",".join(schema.get(f, str(f)) for f in b["fields"])
        print(f"  blob {b['type']} колонка {cols} ndv={b['properties'].get('ndv')}")
print("partition-statistics:", len(meta.get("partition-statistics", [])))
if not stats:
    sys.exit(0)

# Сам Puffin: Magic | блобы | футер. Футер это Magic, JSON, длина JSON (4 байта LE),
# флаги (4 байта), Magic. Читаем хвост файла и разбираем JSON футера.
s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:8333", region_name="us-east-1",
                  aws_access_key_id="admin", aws_secret_access_key="password123")
bucket, key = stats[-1]["statistics-path"].removeprefix("s3://").split("/", 1)
obj = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
print()
print("Puffin: первые 4 байта", obj[:4], "последние 4 байта", obj[-4:])
payload_size, flags = struct.unpack("<ii", obj[-12:-4])
print("длина JSON футера", payload_size, "флаги", flags, "(0 значит футер не сжат)")
footer = json.loads(obj[-12 - payload_size:-12])
print("properties футера:", footer.get("properties"))
for b in footer["blobs"][:3]:
    print(" ", {k: b.get(k) for k in ("type", "fields", "offset", "length", "compression-codec", "properties")})
if len(footer["blobs"]) > 3:
    print("  ... всего блобов", len(footer["blobs"]))
