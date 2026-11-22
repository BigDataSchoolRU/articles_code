# pyspark==3.5.7, pyarrow==25.0.1 | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; ловушка описана в habr.com/ru/articles/1087386
"""Ловушка PySpark: F.lit(datetime(...)) переводится через часовой пояс процесса Python.

Процесс Python живёт в UTC+3 (как VM автора первоисточника), сессия Spark в UTC.
Наивный datetime превращается в момент 2024-02-29 21:00 UTC, и фильтр по колонке
без часового пояса захватывает лишние три часа. Исправление: строковый литерал с cast('timestamp_ntz').
Без Java скрипт считает только эталон pyarrow, печатает SKIP и завершается с кодом 0.
"""
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)
# Часовой пояс процесса задаём явно, чтобы ловушка воспроизводилась на любой машине
os.environ["TZ"] = "Europe/Moscow"
time.tzset()
os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

SRC = "data/orders_small.parquet"
CUTOFF = datetime(2024, 3, 1)


def java_available() -> bool:
    home = os.environ.get("JAVA_HOME")
    if home and Path(home, "bin", "java").exists():
        return True
    return shutil.which("java") is not None


def main() -> None:
    if not Path(SRC).exists():
        raise SystemExit(f"нет {SRC}: сначала запустите 01_gen_data.py")

    # Эталон без Spark: сравнение наивных timestamp в Arrow, без часовых поясов
    ts = pq.read_table(SRC, columns=["ts"]).column("ts")
    mask = pc.greater_equal(ts, pa.scalar(CUTOFF, type=pa.timestamp("us")))
    reference = pc.sum(pc.cast(mask, pa.int64())).as_py()

    if not java_available():
        # Без JVM SparkSession не стартует (JAVA_GATEWAY_EXITED); показываем эталон и выходим
        print(f"эталон pyarrow: {reference:,} строк с ts >= 2024-03-01 00:00:00")
        print("SKIP: java не найдена (ни JAVA_HOME, ни PATH), часть со Spark не запускалась; нужна Java 11 или 17")
        return

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = (SparkSession.builder.master("local[2]").appName("tz-trap")
             .config("spark.driver.memory", "1g")
             .config("spark.ui.enabled", "false")
             .config("spark.sql.session.timeZone", "UTC")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    try:
        df = spark.read.parquet(SRC).select("ts")
        print(f"pyspark {spark.version}, тип колонки ts в Spark: {df.schema['ts'].dataType.simpleString()}")

        naive_lit = F.lit(CUTOFF)
        shown = spark.range(1).select(naive_lit.cast("string").alias("v")).first()["v"]
        print(f"F.lit(datetime(2024, 3, 1)) в сессии UTC превращается в: {shown}")

        naive = df.filter(F.col("ts") >= naive_lit).count()
        # Исправление: литерал без часового пояса, сравнение NTZ с NTZ
        fixed = df.filter(F.col("ts") >= F.lit("2024-03-01 00:00:00").cast("timestamp_ntz")).count()
    finally:
        spark.stop()

    print(f"{'вариант':42} {'строк':>10} {'разница с эталоном':>20}")
    for label, value in (("эталон pyarrow", reference),
                         ("Spark, F.lit(datetime)", naive),
                         ("Spark, F.lit(str).cast('timestamp_ntz')", fixed)):
        print(f"{label:42} {value:>10,} {value - reference:>+20,}")
    print("итог: " + ("исправленный фильтр совпадает с эталоном" if fixed == reference else "ИСПРАВЛЕНИЕ НЕ СОШЛОСЬ"))


if __name__ == "__main__":
    main()
