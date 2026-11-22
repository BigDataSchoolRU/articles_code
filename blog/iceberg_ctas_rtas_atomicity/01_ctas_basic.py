# pyspark 3.5.6, iceberg-spark-runtime-3.5_2.12 1.10.1; код написан для статьи iceberg_ctas_rtas_atomicity по документации Iceberg spark-ddl (nightly), не копия сниппетов Dremio
"""Сценарий 1. Базовый CTAS в именованном каталоге SparkCatalog.

SHOW TABLES, метатаблица snapshots, файлы метаданных и проверка того,
что CTAS не переносит partition spec и TBLPROPERTIES источника.
"""
import os
import shutil
import sys
from pathlib import Path

from pyspark.sql import SparkSession

ICEBERG_VERSION = "1.10.1"
ICEBERG_PACKAGE = f"org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:{ICEBERG_VERSION}"
DEMO = "01_ctas_basic"
BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # все пути дальше относительные, от каталога статьи
ROOT = Path("data") / DEMO
# 'owner' в Spark 3.5 зарезервированное свойство (UNSUPPORTED_FEATURE.SET_TABLE_PROPERTY), берём 'team'
KEYS = ("team", "history.expire.max-snapshot-age-ms", "quality")

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
        # lake: отдельный именованный каталог Iceberg (SparkCatalog); type=hadoop только для учебного стенда
        .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.lake.type", "hadoop")
        .config("spark.sql.catalog.lake.warehouse", (BASE / ROOT / "lake").as_uri())
        # spark_catalog: Iceberg поверх встроенного session catalog (SparkSessionCatalog)
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


def show_snapshots(spark, table):
    spark.sql(
        f"""SELECT snapshot_id, parent_id, operation,
                   summary['added-records'] AS added_records,
                   summary['total-records'] AS total_records
            FROM {table}.snapshots ORDER BY committed_at"""
    ).show(truncate=False)


def metadata_files(table_dir):
    meta = table_dir / "metadata"
    if not meta.exists():
        return []
    return sorted(
        p.name for p in meta.iterdir()
        if p.is_file() and (p.name.endswith(".metadata.json") or p.name == "version-hint.text")
    )


def main():
    spark = build_spark()
    try:
        step("1. CTAS исходной таблицы lake.db.orders_src: PARTITIONED BY (region), TBLPROPERTIES team")
        spark.sql("CREATE NAMESPACE IF NOT EXISTS lake.db")
        spark.sql(SOURCE_SQL.format(rows=10000))
        print("SHOW TABLES IN lake.db:")
        spark.sql("SHOW TABLES IN lake.db").show(truncate=False)
        print("Метатаблица snapshots после CTAS:")
        show_snapshots(spark, "lake.db.orders_src")
        src_dir = ROOT / "lake" / "db" / "orders_src"
        print(f"Каталог таблицы: {src_dir.as_posix()}")
        print(f"Файлы метаданных: {metadata_files(src_dir)}")

        step("2. CTAS-копия без PARTITIONED BY и TBLPROPERTIES")
        spark.sql("CREATE TABLE lake.db.orders_copy USING iceberg AS SELECT * FROM lake.db.orders_src")

        step("3. CTAS-копия, где spec и свойства заданы явно")
        spark.sql(
            """CREATE TABLE lake.db.orders_copy_explicit
               USING iceberg
               PARTITIONED BY (region)
               TBLPROPERTIES ('team' = 'sales', 'history.expire.max-snapshot-age-ms' = '604800000')
               AS SELECT * FROM lake.db.orders_src"""
        )

        step("4. Что унаследовали копии")
        for t in ("lake.db.orders_src", "lake.db.orders_copy", "lake.db.orders_copy_explicit"):
            n = spark.sql(f"SELECT count(*) AS n FROM {t}").first()["n"]
            print(f"{t}: строк {n}; партиционирование: {partitioning(spark, t)}; свойства: {props(spark, t)}")
        same = partitioning(spark, "lake.db.orders_copy") == partitioning(spark, "lake.db.orders_src")
        print("Вывод: CTAS без PARTITIONED BY " + ("сохранил spec источника" if same else "не перенёс spec источника"))
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
