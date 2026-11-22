# pyspark 3.5.6, iceberg-spark-runtime-3.5_2.12 1.10.1; замер написан для статьи iceberg_ctas_rtas_atomicity, цифры локального стенда, не бенчмарк
"""Сценарий 6. Один и тот же сценарий двумя способами: полная пересборка витрины.

RTAS (CREATE OR REPLACE TABLE ... AS SELECT) против INSERT OVERWRITE в готовую таблицу.
Замеряем время прогонов, считаем snapshots, смотрим parent_id, операции и spec.
"""
import os
import shutil
import statistics
import sys
import time
from pathlib import Path

from pyspark.sql import SparkSession

ICEBERG_VERSION = "1.10.1"
ICEBERG_PACKAGE = f"org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:{ICEBERG_VERSION}"
DEMO = "06_compare_rtas_vs_overwrite"
BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # все пути дальше относительные, от каталога статьи
ROOT = Path("data") / DEMO
ROWS = 300000
RUNS = 3

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

MART_SELECT = """
SELECT region, CAST(order_ts AS DATE) AS day, count(*) AS orders, round(sum(amount), 2) AS revenue
FROM lake.db.orders_src
GROUP BY region, CAST(order_ts AS DATE)
"""

RTAS_SQL = f"CREATE OR REPLACE TABLE lake.db.mart_rtas USING iceberg PARTITIONED BY (region) AS {MART_SELECT}"
CREATE_OVERWRITE = """
CREATE TABLE lake.db.mart_overwrite (region STRING, day DATE, orders BIGINT, revenue DOUBLE)
USING iceberg PARTITIONED BY (region)
"""
OVERWRITE_SQL = f"INSERT OVERWRITE lake.db.mart_overwrite {MART_SELECT}"


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
        .config("spark.sql.sources.partitionOverwriteMode", "static")
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


def timed(spark, sql):
    t0 = time.perf_counter()
    spark.sql(sql)
    return (time.perf_counter() - t0) * 1000


def summary(spark, table, table_dir):
    snaps = spark.sql(
        f"SELECT snapshot_id, parent_id, operation FROM {table}.snapshots ORDER BY committed_at"
    ).collect()
    hist = spark.sql(f"SELECT count(*) AS n FROM {table}.history WHERE is_current_ancestor").first()["n"]
    meta = sum(1 for p in table_dir.rglob("*.metadata.json")) if table_dir.exists() else 0
    n = spark.sql(f"SELECT count(*) AS n FROM {table}").first()["n"]
    print(f"  {table}")
    print(f"    строк: {n}; партиционирование: {partitioning(spark, table)}")
    print(f"    snapshots: {len(snaps)}; операции: {[r['operation'] for r in snaps]}")
    print(f"    parent_id есть у {sum(1 for r in snaps if r['parent_id'] is not None)} из {len(snaps)}; "
          f"предков текущего в history: {hist}")
    print(f"    metadata.json в {table_dir.as_posix()}: {meta}")


def main():
    spark = build_spark()
    try:
        step(f"0. Источник: {ROWS} строк, витрина: выручка по region и дню")
        spark.sql("CREATE NAMESPACE IF NOT EXISTS lake.db")
        spark.sql(SOURCE_SQL.format(rows=ROWS))
        # прогрев: первая сборка обеих витрин в замер не входит
        spark.sql(RTAS_SQL)
        spark.sql(CREATE_OVERWRITE)
        spark.sql(OVERWRITE_SQL)

        step(f"1. Замер: {RUNS} прогона каждого варианта, по очереди")
        times = {"RTAS": [], "INSERT OVERWRITE": []}
        for _ in range(RUNS):
            times["RTAS"].append(timed(spark, RTAS_SQL))
            times["INSERT OVERWRITE"].append(timed(spark, OVERWRITE_SQL))
        header = "  вариант            " + "".join(f"прогон {i + 1:<4}" for i in range(RUNS)) + "медиана, мс"
        print(header)
        for name, vals in times.items():
            cells = "".join(f"{v:>8.0f}   " for v in vals)
            print(f"  {name:<19}{cells}{statistics.median(vals):>8.0f}")

        step("2. Что осталось в метаданных")
        summary(spark, "lake.db.mart_rtas", ROOT / "lake" / "db" / "mart_rtas")
        summary(spark, "lake.db.mart_overwrite", ROOT / "lake" / "db" / "mart_overwrite")

        step("3. Совпадает ли результат")
        diff = spark.sql(
            "SELECT count(*) AS n FROM (SELECT * FROM lake.db.mart_rtas EXCEPT SELECT * FROM lake.db.mart_overwrite)"
        ).first()["n"]
        print(f"  строк, которые есть в mart_rtas и нет в mart_overwrite: {diff}")
        print("  оговорка: local[2] и учебный каталог hadoop на локальном диске, цифры показывают порядок, не продакшен")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
