# pyspark 3.5.6, iceberg-spark-runtime-3.5_2.12 1.10.1; код написан для статьи iceberg_ctas_rtas_atomicity по документации Iceberg spark-ddl (nightly) и описанию двух шагов у Dremio
"""Сценарий 5. Контраст: CREATE TABLE + INSERT INTO и INSERT OVERWRITE с падением.

Два шага: между CREATE и INSERT потребитель видит пустую таблицу,
а после упавшего INSERT пустая таблица остаётся. INSERT OVERWRITE с падением
не трогает данные, схему и spec.
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
DEMO = "05_two_step_and_overwrite"
BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # все пути дальше относительные, от каталога статьи
ROOT = Path("data") / DEMO
PATH_RE = re.compile(r"(file:|(?<![\w.])/[\w.\-]+/)")
FAIL_AT = 7000
TABLE = "lake.db.mart_two_step"

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

CREATE_EMPTY = """
CREATE TABLE lake.db.mart_two_step (
  order_id BIGINT, customer_id BIGINT, amount DOUBLE, order_ts TIMESTAMP, region STRING
) USING iceberg
PARTITIONED BY (region)
TBLPROPERTIES ('team' = 'sales')
"""

FAIL_SELECT = "SELECT boom_at(order_id), customer_id, amount, order_ts, region FROM lake.db.orders_src"
OK_SELECT = "SELECT order_id, customer_id, amount, order_ts, region FROM lake.db.orders_src"


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
        # static: INSERT OVERWRITE без PARTITION заменяет всю таблицу
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


def boom_at(order_id):
    if order_id == FAIL_AT:
        raise RuntimeError(f"INJECTED_FAILURE at order_id={order_id}")
    return order_id


def short_err(e):
    lines = [line.strip() for line in str(e).splitlines() if line.strip()]
    pick = next((line for line in lines if "INJECTED_FAILURE" in line), None)
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


def consumer_view(spark):
    # так таблицу видит потребитель, который пришёл в этот момент
    names = {r["tableName"] for r in spark.sql("SHOW TABLES IN lake.db").collect()}
    n = spark.sql(f"SELECT count(*) AS n FROM {TABLE}").first()["n"]
    snaps = spark.sql(f"SELECT count(*) AS n FROM {TABLE}.snapshots").first()["n"]
    v = {
        "в SHOW TABLES": "mart_two_step" in names,
        "строк": n,
        "snapshots": snaps,
        "текущий snapshot": current_snapshot(spark, TABLE),
        "схема": spark.table(TABLE).schema.simpleString(),
        "партиционирование": partitioning(spark, TABLE),
    }
    for k, val in v.items():
        print(f"  {k}: {val}")
    return v


def run_failing(spark, sql):
    try:
        spark.sql(sql)
        print("  запрос неожиданно прошёл")
    except Exception as e:
        print(f"  запрос упал: {short_err(e)}")


def main():
    spark = build_spark()
    try:
        spark.sql("CREATE NAMESPACE IF NOT EXISTS lake.db")
        spark.sql(SOURCE_SQL.format(rows=10000))
        spark.udf.register("boom_at", boom_at, LongType())

        step("1. Шаг первый: CREATE TABLE с явной схемой и spec")
        spark.sql(CREATE_EMPTY)
        consumer_view(spark)
        print("  между CREATE и INSERT витрина уже видна и пуста")

        step(f"2. Шаг второй: INSERT INTO, который падает на order_id={FAIL_AT}")
        run_failing(spark, f"INSERT INTO {TABLE} {FAIL_SELECT}")
        v = consumer_view(spark)
        print("  итог: " + ("пустая таблица осталась в каталоге" if v["в SHOW TABLES"] and v["строк"] == 0
                           else "состояние отличается от ожидаемого, см. строки выше"))

        step("3. Успешный INSERT INTO")
        spark.sql(f"INSERT INTO {TABLE} {OK_SELECT}")
        before = consumer_view(spark)

        step(f"4. INSERT OVERWRITE, который падает на order_id={FAIL_AT}")
        run_failing(spark, f"INSERT OVERWRITE {TABLE} {FAIL_SELECT}")
        after = consumer_view(spark)
        for k in ("строк", "текущий snapshot", "схема", "партиционирование"):
            print(f"  {k}: {'не изменилось' if before[k] == after[k] else 'ИЗМЕНИЛОСЬ'}")

        step("5. Успешный INSERT OVERWRITE только с EU")
        spark.sql(f"INSERT OVERWRITE {TABLE} {OK_SELECT} WHERE region = 'EU'")
        final = consumer_view(spark)
        print(f"  spec после INSERT OVERWRITE: {'сохранён' if final['партиционирование'] == before['партиционирование'] else 'изменился'}")
        spark.sql(
            f"""SELECT snapshot_id, parent_id, operation,
                       summary['added-records'] AS added_records,
                       summary['deleted-records'] AS deleted_records,
                       summary['total-records'] AS total_records
                FROM {TABLE}.snapshots ORDER BY committed_at"""
        ).show(truncate=False)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
