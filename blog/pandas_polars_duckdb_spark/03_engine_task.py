# pandas==3.0.6, polars==1.44.2, duckdb==1.5.5, pyspark==3.5.7 | собственный код bigdataschool для статьи pandas_polars_duckdb_spark; задача повторяет методику habr.com/ru/articles/1087386
"""Одна и та же задача в выбранном движке: filter -> join со справочником -> groupby -> запись Parquet.

Запуск: 03_engine_task.py <engine> <small|large>
engine: pandas, polars_eager, polars_lazy, polars_streaming, duckdb, spark_default, spark_tuned
Последняя строка вывода: RESULT {json} для 04_bench_matrix.py.
Без Java варианты spark_* печатают SKIP и завершаются с кодом 3.
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)
# Слабая машина: 2 ядра. Ставим до импорта движков, иначе пулы потоков уже созданы
os.environ.setdefault("POLARS_MAX_THREADS", "2")
os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
if hasattr(os, "sched_setaffinity"):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:2])

SOURCES = {"small": "data/orders_small.parquet", "large": "data/orders_large.parquet"}
PRODUCTS = "data/products.parquet"
# Ровно те колонки, что нужны задаче: projection вместо чтения всех 9
COLS = ["product_id", "ts", "status", "qty", "price", "discount"]
CUTOFF = datetime(2024, 3, 1)
CUTOFF_SQL = "2024-03-01 00:00:00"
# 60% от бюджета 2 ГБ, как советует OOM-гайд DuckDB для контейнеров и VM
DUCKDB_MEMORY_LIMIT = "1200MB"
NO_JAVA_RC = 3


def java_available() -> bool:
    # PySpark ищет java в JAVA_HOME/bin, затем в PATH
    home = os.environ.get("JAVA_HOME")
    if home and Path(home, "bin", "java").exists():
        return True
    return shutil.which("java") is not None


def run_pandas(src, out):
    import pandas as pd
    df = pd.read_parquet(src, columns=COLS)
    prod = pd.read_parquet(PRODUCTS, columns=["product_id", "category"])
    # Eager: каждая строка ниже материализует новый DataFrame в памяти
    df = df[(df["ts"] >= pd.Timestamp(CUTOFF)) & (df["status"] != "CANCELLED")]
    df = df.merge(prod, on="product_id", how="inner")
    df["revenue"] = df["qty"] * df["price"] * (1 - df["discount"])
    res = (df.groupby("category", as_index=False)
             .agg(n_orders=("revenue", "size"), revenue=("revenue", "sum"),
                  avg_qty=("qty", "mean"), max_price=("price", "max"))
             .sort_values("category"))
    res.to_parquet(out, index=False)
    return len(res), float(res["revenue"].sum()), int(res["n_orders"].sum()), 0.0


def polars_query(frame, prod):
    import polars as pl
    # Один и тот же код работает и на DataFrame (eager), и на LazyFrame (план)
    return (frame.filter((pl.col("ts") >= CUTOFF) & (pl.col("status") != "CANCELLED"))
                 .join(prod, on="product_id", how="inner")
                 .with_columns((pl.col("qty") * pl.col("price") * (1 - pl.col("discount"))).alias("revenue"))
                 .group_by("category")
                 .agg(pl.len().alias("n_orders"), pl.col("revenue").sum(),
                      pl.col("qty").mean().alias("avg_qty"), pl.col("price").max().alias("max_price"))
                 .sort("category"))


def polars_finish(res, out):
    res.write_parquet(out)
    return res.height, float(res["revenue"].sum()), int(res["n_orders"].sum()), 0.0


def run_polars_eager(src, out):
    import polars as pl
    df = pl.read_parquet(src, columns=COLS)
    prod = pl.read_parquet(PRODUCTS, columns=["product_id", "category"])
    return polars_finish(polars_query(df, prod), out)


def run_polars_lazy(src, out):
    import polars as pl
    # В Polars 1.x collect() по умолчанию выполняет план движком в памяти
    res = polars_query(pl.scan_parquet(src), pl.scan_parquet(PRODUCTS)).collect()
    return polars_finish(res, out)


def run_polars_streaming(src, out):
    import polars as pl
    # Streaming-движок обрабатывает батчами; неподдерживаемые узлы уходят в движок в памяти
    res = polars_query(pl.scan_parquet(src), pl.scan_parquet(PRODUCTS)).collect(engine="streaming")
    return polars_finish(res, out)


def run_duckdb(src, out):
    import duckdb
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{DUCKDB_MEMORY_LIMIT}'")
    con.execute("SET threads = 2")
    con.execute("SET preserve_insertion_order = false")
    con.execute("SET temp_directory = 'data/duckdb_tmp'")
    # SQL прямо по read_parquet: DuckDB сам прочитает только упомянутые колонки
    query = f"""
        SELECT p.category,
               count(*) AS n_orders,
               sum(o.qty * o.price * (1 - o.discount)) AS revenue,
               avg(o.qty) AS avg_qty,
               max(o.price) AS max_price
        FROM read_parquet('{src}') o
        JOIN read_parquet('{PRODUCTS}') p USING (product_id)
        WHERE o.ts >= TIMESTAMP '{CUTOFF_SQL}' AND o.status <> 'CANCELLED'
        GROUP BY p.category
        ORDER BY p.category"""
    con.execute(f"COPY ({query}) TO '{out}' (FORMAT parquet)")
    groups, revenue, n_orders = con.execute(
        f"SELECT count(*), sum(revenue), sum(n_orders) FROM read_parquet('{out}')").fetchone()
    con.close()
    return int(groups), float(revenue), int(n_orders), 0.0


def run_spark(src, out, shuffle_partitions):
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    t0 = time.perf_counter()
    builder = (SparkSession.builder.master("local[2]").appName("bench")
               .config("spark.driver.memory", "1g")
               .config("spark.ui.enabled", "false")
               .config("spark.sql.session.timeZone", "UTC"))
    if shuffle_partitions is not None:
        # По умолчанию 200 партиций shuffle: на одной машине это 200 мелких задач
        builder = builder.config("spark.sql.shuffle.partitions", str(shuffle_partitions))
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    # Старт сессии (JVM, контекст) меряем отдельно: автор первоисточника его не учитывал
    start_s = time.perf_counter() - t0
    try:
        o = spark.read.parquet(src).select(*COLS)
        p = spark.read.parquet(PRODUCTS).select("product_id", "category")
        # Литерал строкой с cast в timestamp_ntz: без сдвига часового пояса (см. 07_spark_timezone_trap.py)
        res = (o.filter((F.col("ts") >= F.lit(CUTOFF_SQL).cast("timestamp_ntz")) & (F.col("status") != "CANCELLED"))
                .join(p, "product_id")
                .withColumn("revenue", F.col("qty") * F.col("price") * (1 - F.col("discount")))
                .groupBy("category")
                .agg(F.count("*").alias("n_orders"), F.sum("revenue").alias("revenue"),
                     F.avg("qty").alias("avg_qty"), F.max("price").alias("max_price"))
                .orderBy("category"))
        res.coalesce(1).write.mode("overwrite").parquet(out)
        stats = spark.read.parquet(out).agg(F.count("*"), F.sum("revenue"), F.sum("n_orders")).first()
        return int(stats[0]), float(stats[1]), int(stats[2]), start_s
    finally:
        spark.stop()


RUNNERS = {
    "pandas": run_pandas,
    "polars_eager": run_polars_eager,
    "polars_lazy": run_polars_lazy,
    "polars_streaming": run_polars_streaming,
    "duckdb": run_duckdb,
    "spark_default": lambda s, o: run_spark(s, o, None),
    "spark_tuned": lambda s, o: run_spark(s, o, 4),
}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in RUNNERS or sys.argv[2] not in SOURCES:
        print(f"usage: 03_engine_task.py <{'|'.join(RUNNERS)}> <small|large>")
        sys.exit(2)
    engine, size = sys.argv[1], sys.argv[2]
    src = SOURCES[size]
    if not Path(src).exists():
        print(f"нет {src}: сначала запустите 01_gen_data.py")
        sys.exit(2)
    if engine.startswith("spark") and not java_available():
        # Без JVM PySpark падает с JAVA_GATEWAY_EXITED; сообщаем причину сразу
        print(f"SKIP {engine}: java не найдена (ни JAVA_HOME, ни PATH), нужна Java 11 или 17")
        sys.exit(NO_JAVA_RC)
    Path("results").mkdir(exist_ok=True)
    out = f"results/{engine}_{size}.parquet"
    t0 = time.perf_counter()
    groups, revenue, n_orders, start_s = RUNNERS[engine](src, out)
    wall_s = time.perf_counter() - t0
    result = {"engine": engine, "size": size, "wall_s": round(wall_s, 3),
              "start_s": round(start_s, 3), "task_s": round(wall_s - start_s, 3),
              "groups": groups, "n_orders": n_orders, "revenue": round(revenue, 2), "out": out}
    print(f"{engine} на {src}: {wall_s:.2f} с всего, из них старт сессии {start_s:.2f} с; "
          f"групп {groups}, заказов {n_orders:,}, выручка {revenue:,.2f}; результат в {out}")
    print("RESULT " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
