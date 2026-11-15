# pypaimon 2.1.0 (Apache Paimon 2.1.0), pyarrow 19.0.1, Python 3.12.3, прогнано на стенде 2026-11-15
"""Таблица Apache Paimon с первичным ключом: два коммита upsert'ов, снапшоты, файлы LSM и changelog.

Каталог filesystem лежит в локальной папке, JVM и кластер не нужны.
Путь к хранилищу задаётся переменной PAIMON_WAREHOUSE, по умолчанию ./warehouse рядом со скриптом.
"""
import json
import os
import shutil
from importlib.metadata import version

import pyarrow as pa
from pypaimon import CatalogFactory, Schema

HERE = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE = os.environ.get("PAIMON_WAREHOUSE", os.path.join(HERE, "warehouse"))
TABLE = "shop.orders"

SCHEMA = pa.schema([
    pa.field("order_id", pa.int64(), nullable=False),
    ("customer", pa.string()),
    ("status", pa.string()),
    ("amount", pa.float64()),
])


def write_commit(table, rows):
    """Один пакет строк = один коммит = один новый снапшот."""
    wb = table.new_batch_write_builder()
    write, commit = wb.new_write(), wb.new_commit()
    write.write_arrow(pa.Table.from_pylist(rows, schema=SCHEMA))
    commit.commit(write.prepare_commit())
    write.close()
    commit.close()


def read_all(table):
    rb = table.new_read_builder()
    return rb.new_read().to_arrow(rb.new_scan().plan().splits()).sort_by("order_id")


def show(title, arrow_table):
    print(f"\n--- {title}: {arrow_table.num_rows} строк")
    print(arrow_table.to_pandas().to_string(index=False))


# Демо начинается с чистой базы shop, чтобы номера снапшотов совпадали с текстом статьи
shutil.rmtree(os.path.join(WAREHOUSE, "shop.db"), ignore_errors=True)
print("pypaimon", version("pypaimon"), "| pyarrow", pa.__version__, "| warehouse:", WAREHOUSE)

catalog = CatalogFactory.create({"warehouse": WAREHOUSE})
catalog.create_database("shop", True)
catalog.create_table(TABLE, Schema.from_pyarrow_schema(
    SCHEMA,
    primary_keys=["order_id"],
    options={
        "bucket": "2",                   # фиксированное число бакетов: ключ -> бакет по хэшу
        "merge-engine": "deduplicate",   # по ключу остаётся последняя версия строки
        "changelog-producer": "input",   # входные записи пишутся ещё и файлами changelog
    }), False)
table = catalog.get_table(TABLE)

# 1. Первый коммит: четыре новых заказа
write_commit(table, [
    {"order_id": 1, "customer": "anna", "status": "created", "amount": 120.0},
    {"order_id": 2, "customer": "boris", "status": "created", "amount": 80.0},
    {"order_id": 3, "customer": "vera", "status": "created", "amount": 45.5},
    {"order_id": 4, "customer": "gleb", "status": "created", "amount": 300.0},
])
show("чтение после коммита 1", read_all(table))

# Потоковый читатель подключается после первого коммита: сначала получает полный снимок,
# дальше только изменения новых снапшотов
srb = table.new_stream_read_builder().with_include_row_kind(True)
stream = srb.new_streaming_scan().stream_sync()
initial = next(stream)
print(f"\n--- потоковый читатель: стартовый план по снапшоту {initial.snapshot_id}, "
      f"строк {srb.new_read().to_arrow(initial.splits()).num_rows}")

# 2. Второй коммит: апдейты, два изменения одного ключа в одном пакете и новый заказ
write_commit(table, [
    {"order_id": 2, "customer": "boris", "status": "paid", "amount": 80.0},
    {"order_id": 3, "customer": "vera", "status": "cancelled", "amount": 45.5},
    {"order_id": 2, "customer": "boris", "status": "shipped", "amount": 80.0},
    {"order_id": 5, "customer": "dina", "status": "created", "amount": 15.0},
])
show("чтение после коммита 2 (merge-on-read, последняя версия по ключу)", read_all(table))

delta = next(stream)
show(f"потоковый читатель: изменения снапшота {delta.snapshot_id} (changelog-producer=input)",
     srb.new_read().to_arrow(delta.splits()))

# 3. Снапшоты: каждый коммит оставляет JSON-файл с номером, видом коммита и счётчиками
table_path = os.path.join(WAREHOUSE, "shop.db", "orders")
print("\n--- снапшоты")
for name in sorted(os.listdir(os.path.join(table_path, "snapshot"))):
    if not name.startswith("snapshot-"):
        continue
    with open(os.path.join(table_path, "snapshot", name)) as f:
        s = json.load(f)
    print(f"{name}: commitKind={s['commitKind']} totalRecordCount={s['totalRecordCount']} "
          f"deltaRecordCount={s['deltaRecordCount']} changelogRecordCount={s.get('changelogRecordCount')}")

# 4. Файлы данных последнего снапшота по бакетам и уровням LSM-дерева
print("\n--- файлы данных последнего снапшота (бакет, уровень LSM, строк, seq-номера)")
for split in sorted(table.new_read_builder().new_scan().plan().splits(), key=lambda s: s.bucket):
    for f in split.files:
        print(f"bucket={split.bucket} level={f.level} rows={f.row_count} "
              f"seq={f.min_sequence_number}..{f.max_sequence_number} {f.file_name}")
    print(f"bucket={split.bucket}: файлов {len(split.files)}, строк в файлах {split.row_count}, "
          f"raw_convertible={split.raw_convertible}")

# 5. Что лежит на диске
print("\n--- каталог таблицы")
for root, dirs, files in sorted(os.walk(table_path)):
    dirs.sort()
    rel = os.path.relpath(root, table_path)
    for name in sorted(files):
        print(os.path.join(rel, name) if rel != "." else name)
