# pyspark 4.0.4, iceberg-spark-runtime-4.0_2.13 1.10.1, прогнано на стенде 2026-10-22
"""NDV от Spark: compute_table_stats пишет Puffin, его потом читает и Spark CBO, и Trino.

Запуск внутри контейнера spark:
  /opt/spark/bin/spark-submit --driver-memory 2g /demo/04_spark_compute_stats.py
"""
import time

from pyspark.sql import SparkSession

spark = (
    SparkSession.builder.appName("compute_table_stats")
    .config("spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    # тот же REST-каталог и то же S3, что у Trino
    .config("spark.sql.catalog.iceberg", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.iceberg.type", "rest")
    .config("spark.sql.catalog.iceberg.uri", "http://rest:8181")
    .config("spark.sql.catalog.iceberg.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .config("spark.sql.catalog.iceberg.s3.endpoint", "http://seaweedfs:8333")
    .config("spark.sql.catalog.iceberg.s3.path-style-access", "true")
    # без CBO Spark не смотрит на статистику колонок
    .config("spark.sql.cbo.enabled", "true")
    .config("spark.sql.cbo.joinReorder.enabled", "true")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("ERROR")
print("Spark", spark.version)


def column_ndv(table: str) -> dict:
    """NDV колонок, которые видит оптимизатор Spark в логическом плане."""
    stats = spark.table(table)._jdf.queryExecution().optimizedPlan().stats()
    result = {}
    it = stats.attributeStats().iterator()
    while it.hasNext():
        pair = it.next()
        cs = pair._2()
        # Оценка join в Spark требует и distinctCount, и nullCount у ключа
        ndv = int(str(cs.distinctCount().get())) if cs.distinctCount().isDefined() else None
        nulls = int(str(cs.nullCount().get())) if cs.nullCount().isDefined() else None
        result[pair._1().name()] = {"distinctCount": ndv, "nullCount": nulls}
    return result


print("статистика колонок в плане Spark до расчёта:", column_ndv("iceberg.tpch.orders"))

# Ключи join и колонки фильтров: считать NDV по всем колонкам дорого и не нужно
targets = {
    "tpch.nation": ["nationkey"],
    "tpch.customer": ["custkey", "nationkey"],
    "tpch.orders": ["orderkey", "custkey", "orderdate"],
    "tpch.lineitem": ["orderkey"],
}
for table, cols in targets.items():
    t = time.time()
    arr = ", ".join(f"'{c}'" for c in cols)
    row = spark.sql(
        f"CALL iceberg.system.compute_table_stats(table => '{table}', columns => array({arr}))"
    ).first()
    print(f"{table}: {time.time() - t:.1f} с, файл {row.statistics_file.rsplit('/', 1)[-1]}")

print("статистика колонок в плане Spark после расчёта:")
for name, cs in column_ndv("iceberg.tpch.orders").items():
    print(" ", name, cs)

# Тот же запрос, что в join_plan.py: смотрим оценки строк в плане Spark
plan = spark.sql("""
EXPLAIN COST
SELECT n.name, count(*) AS lines, sum(l.extendedprice) AS revenue
FROM iceberg.tpch.lineitem l
JOIN iceberg.tpch.orders o   ON l.orderkey = o.orderkey
JOIN iceberg.tpch.customer c ON o.custkey = c.custkey
JOIN iceberg.tpch.nation n   ON c.nationkey = n.nationkey
WHERE o.orderdate >= DATE '1995-01-01' AND o.orderdate < DATE '1995-04-01'
GROUP BY n.name
""").first()[0]
logical = plan.split("== Physical Plan ==")[0]
for line in logical.splitlines():
    if "Join" in line or "RelationV2" in line:
        print(line.strip()[:200])
spark.stop()
