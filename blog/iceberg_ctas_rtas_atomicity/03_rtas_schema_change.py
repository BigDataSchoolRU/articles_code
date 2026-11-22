# pyspark 3.5.6, iceberg-spark-runtime-3.5_2.12 1.10.1; код написан для статьи iceberg_ctas_rtas_atomicity по документации Iceberg spark-ddl (nightly), не копия сниппетов Dremio
"""Сценарий 3. RTAS со сменой схемы и партиционирования.

Показывает схему, spec, свойства (слияние TBLPROPERTIES), history и snapshots,
а затем REPLACE TABLE ... AS SELECT без PARTITIONED BY, который снимает spec.
"""
import os
import shutil
import sys
from pathlib import Path

from pyspark.sql import SparkSession

ICEBERG_VERSION = "1.10.1"
ICEBERG_PACKAGE = f"org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:{ICEBERG_VERSION}"
DEMO = "03_rtas_schema_change"
BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # все пути дальше относительные, от каталога статьи
ROOT = Path("data") / DEMO
# 'owner' в Spark 3.5 зарезервирован, свойство владельца называем 'team'
KEYS = ("team", "history.expire.max-snapshot-age-ms", "quality")
TABLE = "lake.db.sales"

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
CREATE TABLE lake.db.sales
USING iceberg
PARTITIONED BY (region)
TBLPROPERTIES ('team' = 'sales', 'history.expire.max-snapshot-age-ms' = '604800000')
AS SELECT * FROM lake.db.orders_src
"""

# RTAS: убираем customer_id, меняем тип amount, переименовываем region, другой spec и новое свойство
RTAS_NEW_LAYOUT = """
CREATE OR REPLACE TABLE lake.db.sales
USING iceberg
PARTITIONED BY (days(order_ts))
TBLPROPERTIES ('quality' = 'checked')
AS SELECT order_id, CAST(amount AS DECIMAL(12, 2)) AS amount, order_ts, lower(region) AS region_code
FROM lake.db.orders_src WHERE amount > 100
"""

# тот же SELECT, но PARTITIONED BY забыли: spec заменится на пустой
RTAS_NO_SPEC = """
REPLACE TABLE lake.db.sales
USING iceberg
AS SELECT order_id, CAST(amount AS DECIMAL(12, 2)) AS amount, order_ts, lower(region) AS region_code
FROM lake.db.orders_src WHERE amount > 100
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


def props(spark, table):
    rows = {r["key"]: r["value"] for r in spark.sql(f"SHOW TBLPROPERTIES {table}").collect()}
    return {k: rows.get(k, "—") for k in KEYS}


def current_snapshot(spark, table):
    row = spark.sql(f"SELECT snapshot_id FROM {table}.refs WHERE name = 'main'").first()
    return row["snapshot_id"] if row else None


def describe(spark, table):
    n = spark.sql(f"SELECT count(*) AS n FROM {table}").first()["n"]
    print(f"  схема: {spark.table(table).schema.simpleString()}")
    print(f"  партиционирование: {partitioning(spark, table)}")
    print(f"  свойства: {props(spark, table)}")
    print(f"  строк: {n}; текущий snapshot: {current_snapshot(spark, table)}")


def show_history(spark, table):
    print("  history:")
    spark.sql(
        f"SELECT snapshot_id, parent_id, is_current_ancestor FROM {table}.history ORDER BY made_current_at"
    ).show(truncate=False)


def show_snapshots(spark, table):
    print("  snapshots:")
    spark.sql(
        f"""SELECT snapshot_id, parent_id, operation,
                   summary['added-records'] AS added_records,
                   summary['total-records'] AS total_records
            FROM {table}.snapshots ORDER BY committed_at"""
    ).show(truncate=False)


def main():
    spark = build_spark()
    try:
        step("1. Витрина lake.db.sales: PARTITIONED BY (region), TBLPROPERTIES team")
        spark.sql("CREATE NAMESPACE IF NOT EXISTS lake.db")
        spark.sql(SOURCE_SQL.format(rows=10000))
        spark.sql(CREATE_SALES)
        describe(spark, TABLE)
        before_spec = partitioning(spark, TABLE)

        step("2. CREATE OR REPLACE TABLE ... AS SELECT: новая схема, days(order_ts), свойство quality")
        spark.sql(RTAS_NEW_LAYOUT)
        describe(spark, TABLE)
        p = props(spark, TABLE)
        print("  свойство team после RTAS: " + ("сохранилось, свойства слились" if p["team"] != "—" else "пропало"))
        print(f"  spec: было {before_spec}, стало {partitioning(spark, TABLE)}")
        show_history(spark, TABLE)
        show_snapshots(spark, TABLE)

        step("3. REPLACE TABLE ... AS SELECT без PARTITIONED BY")
        spec_before = partitioning(spark, TABLE)
        spark.sql(RTAS_NO_SPEC)
        describe(spark, TABLE)
        print(f"  spec: было {spec_before}, стало {partitioning(spark, TABLE)}")
        show_history(spark, TABLE)
        show_snapshots(spark, TABLE)

        step("4. Время до RTAS доступно через time travel")
        first = spark.sql(f"SELECT snapshot_id FROM {TABLE}.snapshots ORDER BY committed_at LIMIT 1").first()["snapshot_id"]
        old = spark.sql(f"SELECT * FROM {TABLE} VERSION AS OF {first}")
        print(f"  snapshot {first}: строк {old.count()}, схема {old.schema.simpleString()}")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
