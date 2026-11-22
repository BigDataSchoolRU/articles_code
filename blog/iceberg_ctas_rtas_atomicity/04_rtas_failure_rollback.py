# pyspark 3.5.6, iceberg-spark-runtime-3.5_2.12 1.10.1; код написан для статьи iceberg_ctas_rtas_atomicity по документации Iceberg spark-ddl и spark-procedures (nightly), не копия сниппетов Dremio
"""Сценарий 4. RTAS с падением и откат после успешного RTAS.

Сначала RTAS падает посередине: проверяем, что snapshot, строки и схема те же.
Затем успешный RTAS и откат через CALL lake.system.rollback_to_snapshot.
Если процедура откажет, пробуем set_current_snapshot и печатаем, что случилось.
"""
import os
import re
import shutil
import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.types import LongType

ICEBERG_VERSION = "1.10.1"
ICEBERG_PACKAGE = f"org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:{ICEBERG_VERSION}"
DEMO = "04_rtas_failure_rollback"
BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # все пути дальше относительные, от каталога статьи
ROOT = Path("data") / DEMO
PATH_RE = re.compile(r"(file:|(?<![\w.])/[\w.\-]+/)")
FAIL_AT = 7000
TABLE = "lake.db.sales"
TABLE_DIR = ROOT / "lake" / "db" / "sales"

# 'owner' в Spark 3.5 зарезервирован, свойство владельца называем 'team'
SOURCE_SQL = """
CREATE TABLE lake.db.orders_src
USING iceberg
PARTITIONED BY (region)
TBLPROPERTIES ('team' = 'sales', 'history.expire.max-snapshot-age-ms' = '604800000')
AS SELECT
  id AS order_id,
  id % 500 AS customer_id,
  CAST(round(rand(42) * 1000, 2) AS DOUBLE) AS amount,
  timestamp_seconds(1767225600 + id * 60) AS order_ts,
  element_at(array('EU', 'US', 'APAC'), CAST(id % 3 AS INT) + 1) AS region
FROM range(0, {rows})
"""

CREATE_SALES = """
CREATE TABLE lake.db.sales USING iceberg PARTITIONED BY (region)
AS SELECT * FROM lake.db.orders_src
"""

RTAS_FAIL = """
CREATE OR REPLACE TABLE lake.db.sales USING iceberg PARTITIONED BY (days(order_ts))
AS SELECT boom_at(order_id) AS order_id, amount, order_ts, lower(region) AS region_code
FROM lake.db.orders_src
"""

# успешный RTAS: только EU, без customer_id, с новой колонкой region_code; тип amount тот же
RTAS_OK = """
CREATE OR REPLACE TABLE lake.db.sales USING iceberg PARTITIONED BY (days(order_ts))
AS SELECT order_id, amount, order_ts, lower(region) AS region_code
FROM lake.db.orders_src WHERE region = 'EU'
"""


def build_spark():
    # чистый стенд на каждый запуск: у каждого каталога свой warehouse внутри data/
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
    spark = (
        SparkSession.builder.master("local[2]")
        .appName(DEMO)
        .config("spark.driver.memory", "2g")
        .config("spark.jars.packages", ICEBERG_PACKAGE)
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.lake.type", "hadoop")
        .config("spark.sql.catalog.lake.warehouse", (BASE / ROOT / "lake").as_uri())
        .config("spark.sql.catalog.spark_catalog", "org.apache.iceberg.spark.SparkSessionCatalog")
        .config("spark.sql.catalog.spark_catalog.type", "hadoop")
        .config("spark.sql.catalog.spark_catalog.warehouse", (BASE / ROOT / "session").as_uri())
        .config("spark.sql.catalogImplementation", "in-memory")
        .config("spark.sql.warehouse.dir", (BASE / ROOT / "spark").as_uri())
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def boom_at(order_id):
    if order_id == FAIL_AT:
        raise RuntimeError(f"INJECTED_FAILURE at order_id={order_id}")
    return order_id


def short_err(e):
    lines = [line.strip() for line in str(e).splitlines() if line.strip()]
    pick = next((line for line in lines if "INJECTED_FAILURE" in line), None)
    if pick is None:
        causes = [line for line in lines if line.startswith("Caused by:")]
        pick = causes[-1] if causes else None
    if pick is None:
        pick = next((line for line in lines if re.search(r"(Exception|Error)\b", line) and not line.startswith("at ")),
                    lines[0] if lines else "")
    pick = PATH_RE.split(pick, maxsplit=1)[0].strip()
    return f"{type(e).__name__}: {pick[:200]}"


def step(title):
    print(f"\n--- {title} ---", flush=True)


def partitioning(spark, table):
    # Spark 3.5: только identity-партиции идут в '# Partition Information' именами колонок,
    # с трансформами (days, bucket) — в '# Partitioning' строками 'Part N'
    rows = spark.sql(f"DESCRIBE TABLE {table}").collect()
    parts, section = [], None
    for r in rows:
        name = (r["col_name"] or "").strip()
        if not name:
            section = None
        elif name == "# Partition Information":
            section = "identity"
        elif name == "# Partitioning":
            section = "transform"
        elif name.startswith("# col_name"):
            continue
        elif name.startswith("#"):
            section = None
        elif section == "identity":
            parts.append(name)
        elif section == "transform" and name.startswith("Part "):
            parts.append(r["data_type"])
    return ", ".join(parts) if parts else "без партиционирования"


def current_snapshot(spark, table):
    row = spark.sql(f"SELECT snapshot_id FROM {table}.refs WHERE name = 'main'").first()
    return row["snapshot_id"] if row else None


def safe(fn):
    try:
        return fn()
    except Exception as e:
        return f"ошибка, {short_err(e)}"


def state(spark):
    # снимок состояния таблицы: каталог, данные и файлы на диске
    files = [p for p in TABLE_DIR.rglob("*") if p.is_file()] if TABLE_DIR.exists() else []
    return {
        "текущий snapshot": safe(lambda: current_snapshot(spark, TABLE)),
        "строк": safe(lambda: spark.sql(f"SELECT count(*) AS n FROM {TABLE}").first()["n"]),
        "схема": safe(lambda: spark.table(TABLE).schema.simpleString()),
        "партиционирование": safe(lambda: partitioning(spark, TABLE)),
        "snapshots в метаданных": safe(lambda: spark.sql(f"SELECT count(*) AS n FROM {TABLE}.snapshots").first()["n"]),
        "metadata.json на диске": sum(1 for p in files if p.name.endswith(".metadata.json")),
        "parquet на диске": sum(1 for p in files if p.suffix == ".parquet"),
    }


def print_state(st):
    for k, v in st.items():
        print(f"  {k}: {v}")


def compare(before, after):
    for k in before:
        mark = "не изменилось" if before[k] == after[k] else "ИЗМЕНИЛОСЬ"
        print(f"  {k}: до {before[k]}, после {after[k]} ({mark})")


def show_history(spark):
    spark.sql(
        f"SELECT snapshot_id, parent_id, is_current_ancestor FROM {TABLE}.history ORDER BY made_current_at"
    ).show(truncate=False)


def main():
    spark = build_spark()
    try:
        step("1. Витрина lake.db.sales до экспериментов")
        spark.sql("CREATE NAMESPACE IF NOT EXISTS lake.db")
        spark.sql(SOURCE_SQL.format(rows=10000))
        spark.udf.register("boom_at", boom_at, LongType())
        spark.sql(CREATE_SALES)
        original = state(spark)
        print_state(original)
        original_snapshot = original["текущий snapshot"]

        step(f"2. RTAS, который падает на order_id={FAIL_AT}")
        try:
            spark.sql(RTAS_FAIL)
            print("  RTAS неожиданно прошёл")
        except Exception as e:
            print(f"  RTAS упал: {short_err(e)}")
        after_fail = state(spark)
        compare(original, after_fail)
        extra = after_fail["parquet на диске"] - original["parquet на диске"]
        print(f"  лишних parquet-файлов после сбоя: {extra} (кандидаты в orphan-файлы)")

        step("3. Успешный RTAS: только EU, другая схема и spec")
        spark.sql(RTAS_OK)
        print_state(state(spark))
        print("  history после RTAS:")
        show_history(spark)

        step(f"4. Откат на snapshot {original_snapshot} через rollback_to_snapshot")
        try:
            spark.sql(
                f"CALL lake.system.rollback_to_snapshot(table => 'db.sales', snapshot_id => {original_snapshot})"
            ).show(truncate=False)
            print("  rollback_to_snapshot выполнен")
        except Exception as e:
            print(f"  rollback_to_snapshot отказал: {short_err(e)}")
            print("  пробуем set_current_snapshot: он не требует, чтобы snapshot был предком текущего")
            try:
                spark.sql(
                    f"CALL lake.system.set_current_snapshot(table => 'db.sales', snapshot_id => {original_snapshot})"
                ).show(truncate=False)
                print("  set_current_snapshot выполнен")
            except Exception as e2:
                print(f"  set_current_snapshot тоже отказал: {short_err(e2)}")

        step("5. Состояние после отката")
        spark.sql(f"REFRESH TABLE {TABLE}")
        restored = state(spark)
        compare(original, restored)
        print("  первые строки текущего состояния:")
        try:
            spark.sql(f"SELECT * FROM {TABLE} ORDER BY order_id LIMIT 3").show(truncate=False)
        except Exception as e:
            print(f"  SELECT упал: {short_err(e)}")
        print("  те же строки через VERSION AS OF исходного snapshot:")
        old_sql = f"SELECT * FROM {TABLE} VERSION AS OF {original_snapshot} ORDER BY order_id LIMIT 3"
        try:
            spark.sql(old_sql).show(truncate=False)
        except Exception as e:
            print(f"  VERSION AS OF упал: {short_err(e)}")
            print("  повтор с spark.sql.iceberg.vectorization.enabled=false")
            spark.conf.set("spark.sql.iceberg.vectorization.enabled", "false")
            try:
                spark.sql(old_sql).show(truncate=False)
            except Exception as e2:
                print(f"  без векторизации тоже упал: {short_err(e2)}")
        print("  history после отката:")
        show_history(spark)
        # set_current_snapshot двигает указатель данных; схема и spec таблицы остаются текущими
        for key in ("строк", "схема", "партиционирование"):
            mark = "как до RTAS" if restored[key] == original[key] else "НЕ как до RTAS"
            print(f"  итог, {key}: {mark}")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
