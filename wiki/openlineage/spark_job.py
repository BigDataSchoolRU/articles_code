# Apache Spark 4.0.4 (Scala 2.13, Java 17) + openlineage-spark_2.13 1.55.0, прогнано на стенде 2026-11-12
"""Обычное Spark-задание: выручка по клиентам из CSV в Parquet.

В коде нет ни строки OpenLineage. События START, RUNNING и COMPLETE с входом, выходом,
схемой и колоночным lineage отправляет OpenLineageSparkListener, подключённый через
spark-submit (--jars и --conf spark.extraListeners, см. compose.yaml).
"""
import sys
from pathlib import Path

from pyspark.sql import SparkSession

HERE = Path(__file__).resolve().parent
SRC = str(HERE / "data" / "orders.csv")
OUT = "/tmp/lake/customer_revenue"   # внутри контейнера, папка проекта смонтирована только на чтение

spark = SparkSession.builder.appName("customer_revenue").getOrCreate()

orders = (spark.read.option("header", True)
          .schema("order_id INT, customer STRING, order_ts TIMESTAMP, amount DECIMAL(10,2), status STRING")
          .csv(SRC))
orders.createOrReplaceTempView("orders")

revenue = spark.sql("""
    SELECT customer,
           count(order_id)            AS orders,
           sum(amount)                AS revenue,
           max(CAST(order_ts AS DATE)) AS last_order_day
    FROM orders
    WHERE status = 'paid'
    GROUP BY customer
""")
revenue.write.mode("overwrite").parquet(OUT)

spark.read.parquet(OUT).orderBy("customer").show(truncate=False)
spark.stop()
sys.exit(0)
