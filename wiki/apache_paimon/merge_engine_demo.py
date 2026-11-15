# pypaimon 2.1.0 (Apache Paimon 2.1.0), pyarrow 19.0.1, Python 3.12.3, прогнано на стенде 2026-11-15
"""Одна и та же последовательность записей в четыре таблицы Apache Paimon с разным merge engine.

Три коммита по одному ключу: заказ создан, затем пришёл только статус, затем только доплата.
Пустые поля (None) в записях 2 и 3 означают «это поле в событии не пришло».
"""
import os
import shutil

import pyarrow as pa
from pypaimon import CatalogFactory, Schema

HERE = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE = os.environ.get("PAIMON_WAREHOUSE", os.path.join(HERE, "warehouse"))

SCHEMA = pa.schema([
    pa.field("order_id", pa.int64(), nullable=False),
    ("customer", pa.string()),
    ("status", pa.string()),
    ("amount", pa.float64()),
])

COMMITS = [
    [{"order_id": 1, "customer": "anna", "status": "created", "amount": 100.0}],
    [{"order_id": 1, "customer": None, "status": "paid", "amount": None}],
    [{"order_id": 1, "customer": None, "status": None, "amount": 25.0}],
]

ENGINES = {
    "deduplicate": {"merge-engine": "deduplicate"},
    "partial_update": {"merge-engine": "partial-update"},
    "aggregation": {
        "merge-engine": "aggregation",
        "fields.amount.aggregate-function": "sum",                  # сумма платежей
        "fields.default-aggregate-function": "last_non_null_value",  # остальное: последнее непустое
    },
    "first_row": {"merge-engine": "first-row"},
}

# Каждый запуск с чистой базы engines; база shop из pk_table_demo.py не трогается
shutil.rmtree(os.path.join(WAREHOUSE, "engines.db"), ignore_errors=True)
catalog = CatalogFactory.create({"warehouse": WAREHOUSE})
catalog.create_database("engines", True)

print("последовательность коммитов по ключу order_id=1:")
for i, rows in enumerate(COMMITS, 1):
    print(f"  коммит {i}: {rows[0]}")

print(f"\n{'merge engine':<16}{'customer':<10}{'status':<10}{'amount':>8}")
for name, options in ENGINES.items():
    ident = f"engines.orders_{name}"
    try:
        catalog.create_table(ident, Schema.from_pyarrow_schema(
            SCHEMA, primary_keys=["order_id"], options={"bucket": "1", **options}), False)
        table = catalog.get_table(ident)
        for rows in COMMITS:
            wb = table.new_batch_write_builder()
            write, commit = wb.new_write(), wb.new_commit()
            write.write_arrow(pa.Table.from_pylist(rows, schema=SCHEMA))
            commit.commit(write.prepare_commit())
            write.close()
            commit.close()
        rb = table.new_read_builder()
        rows = rb.new_read().to_arrow(rb.new_scan().plan().splits()).to_pylist()
        if rows:
            r = rows[0]
            print(f"{options['merge-engine']:<16}{str(r['customer']):<10}{str(r['status']):<10}{r['amount']:>8}")
        else:
            # first-row: пакетное чтение пропускает уровень 0 LSM, а pypaimon компакцию не делает.
            # Стартовый план потокового чтения уровень 0 включает и показывает, что строка на месте.
            srb = table.new_stream_read_builder()
            plan = next(srb.new_streaming_scan().stream_sync())
            r = srb.new_read().to_arrow(plan.splits()).to_pylist()[0]
            print(f"{options['merge-engine']:<16}пакетное чтение: 0 строк (видит только файлы после компакции)")
            print(f"{'':<16}{str(r['customer']):<10}{str(r['status']):<10}{r['amount']:>8}"
                  "  <- потоковое чтение, уровень 0")
    except Exception as e:  # неподдержанное в Python-клиенте сочетание тоже результат
        print(f"{options['merge-engine']:<16}ОШИБКА {type(e).__name__}: {e}")
