# pyspark 3.5.6, iceberg-spark-runtime-3.5_2.12 1.10.1; код написан для статьи iceberg_ctas_rtas_atomicity по документации Iceberg spark-ddl (nightly), сценарий failure injection по мотивам Dremio
"""Сценарий 2. CTAS, который падает посередине, в двух каталогах одной сессии.

UDF бросает исключение на order_id=7000. После сбоя проверяем три канала:
SHOW TABLES, SELECT count(*) и файлы на диске.
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
DEMO = "02_ctas_failure"
BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # все пути дальше относительные, от каталога статьи
ROOT = Path("data") / DEMO
PATH_RE = re.compile(r"(file:|(?<![\w.])/[\w.\-]+/)")
FAIL_AT = 7000

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

FAIL_SELECT = (
    "SELECT boom_at(order_id) AS order_id, customer_id, amount, order_ts, region "
    "FROM lake.db.orders_src"
)


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
    # падаем на одной строке: другие задачи успевают записать свои data-файлы
    if order_id == FAIL_AT:
        raise RuntimeError(f"INJECTED_FAILURE at order_id={order_id}")
    return order_id


def short_err(e):
    # класс исключения и фраза до первого пути: без путей, PID и интерпретатора
    lines = [line.strip() for line in str(e).splitlines() if line.strip()]
    pick = next((line for line in lines if "INJECTED_FAILURE" in line), None)
    if pick is None:
        pick = next((line for line in lines if re.search(r"(Exception|Error)\b", line) and not line.startswith("at ")),
                    lines[0] if lines else "")
    pick = PATH_RE.split(pick, maxsplit=1)[0].strip()
    return f"{type(e).__name__}: {pick[:200]}"


def step(title):
    print(f"\n--- {title} ---", flush=True)


def disk_summary(path):
    if not path.exists():
        return f"на диске {path.as_posix()}: каталога нет"
    files = [p for p in path.rglob("*") if p.is_file()]
    parquet = sum(1 for p in files if p.suffix == ".parquet")
    meta = sum(1 for p in files if p.name.endswith(".metadata.json"))
    return f"на диске {path.as_posix()}: файлов {len(files)}, parquet {parquet}, metadata.json {meta}"


def probe(spark, catalog, ns, table, path):
    # три независимых канала: листинг каталога, чтение и файловая система
    names = {r["tableName"] for r in spark.sql(f"SHOW TABLES IN {catalog}.{ns}").collect()}
    listed = table in names
    try:
        n = spark.sql(f"SELECT count(*) AS n FROM {catalog}.{ns}.{table}").first()["n"]
        read, readable = f"читается, строк {n}", True
    except Exception as e:
        read, readable = f"не читается, {short_err(e)}", False
    print(f"  {catalog}.{ns}.{table}")
    print(f"    SHOW TABLES: {'есть' if listed else 'нет'}")
    print(f"    SELECT count(*): {read}")
    print(f"    {disk_summary(path)}")
    return listed or readable


def run_failing(spark, sql):
    try:
        spark.sql(sql)
        print("  запрос неожиданно прошёл")
        return False
    except Exception as e:
        print(f"  запрос упал: {short_err(e)}")
        return True


def main():
    spark = build_spark()
    try:
        step(f"0. Источник lake.db.orders_src и UDF boom_at, которая падает на order_id={FAIL_AT}")
        spark.sql("CREATE NAMESPACE IF NOT EXISTS lake.db")
        spark.sql(SOURCE_SQL.format(rows=10000))
        spark.udf.register("boom_at", boom_at, LongType())
        print("  строк в источнике:", spark.sql("SELECT count(*) AS n FROM lake.db.orders_src").first()["n"])

        step("1. Эталон: успешный CTAS в spark_catalog (SparkSessionCatalog)")
        spark.sql(
            "CREATE TABLE spark_catalog.default.ctas_ok_session USING iceberg "
            "AS SELECT * FROM lake.db.orders_src WHERE region = 'EU'"
        )
        probe(spark, "spark_catalog", "default", "ctas_ok_session", ROOT / "session" / "default" / "ctas_ok_session")
        print("  так выглядит успешная таблица в трёх каналах проверки, с этим сравниваем сбои ниже")

        cases = [
            ("lake", "db", "ctas_fail", "iceberg", ROOT / "lake" / "db" / "ctas_fail",
             "SparkCatalog, USING iceberg"),
            ("spark_catalog", "default", "ctas_fail_session", "iceberg",
             ROOT / "session" / "default" / "ctas_fail_session", "SparkSessionCatalog, USING iceberg"),
            ("spark_catalog", "default", "ctas_fail_parquet", "parquet",
             ROOT / "spark" / "ctas_fail_parquet", "SparkSessionCatalog, USING parquet (не Iceberg)"),
        ]
        for i, (catalog, ns, table, fmt, path, label) in enumerate(cases, start=2):
            step(f"{i}. CTAS с падением: {label}")
            run_failing(spark, f"CREATE TABLE {catalog}.{ns}.{table} USING {fmt} AS {FAIL_SELECT}")
            left = probe(spark, catalog, ns, table, path)
            print("  итог: " + ("после сбоя таблица видна, поведение неатомарное" if left
                               else "после сбоя таблицы нет ни в листинге, ни для SELECT"))

        step("5. Повторный CTAS с тем же именем в lake: имя свободно?")
        try:
            spark.sql("CREATE TABLE lake.db.ctas_fail USING iceberg AS SELECT * FROM lake.db.orders_src WHERE region = 'US'")
            print("  повторный CTAS прошёл")
        except Exception as e:
            print(f"  повторный CTAS упал: {short_err(e)}")
        probe(spark, "lake", "db", "ctas_fail", ROOT / "lake" / "db" / "ctas_fail")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
