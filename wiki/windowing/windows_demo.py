# Apache Spark 4.0.4 (PySpark, Structured Streaming), образ apache/spark:4.0.4-scala2.13-java17-python3-ubuntu, прогнано на стенде 2026-11-13
"""Один и тот же поток событий через три типа окон: tumbling, sliding и session.

События лежат в events.jsonl, поле batch говорит, в какой микробатч событие придёт.
Скрипт раскладывает их по файлам, и файловый источник читает по одному файлу за батч,
поэтому watermark двигается между батчами так же, как в живом потоке.
"""
import json
import os
import shutil
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType, TimestampType

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = "/tmp/windowing"          # входные файлы и чекпойнты; папка проекта смонтирована только на чтение
INPUT = f"{WORK}/input"

WATERMARK = "5 minutes"           # насколько позже максимального времени события ждём опоздавших
SIZE, SLIDE, GAP = "10 minutes", "5 minutes", "5 minutes"

SCHEMA = StructType([
    StructField("id", StringType()),
    StructField("user", StringType()),
    StructField("ts", TimestampType()),
])


def prepare_input():
    """Раскладываем события по файлам batch_N.json: один файл это один микробатч."""
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(INPUT)
    batches = {}
    with open(os.path.join(HERE, "events.jsonl")) as f:
        for line in f:
            e = json.loads(line)
            batches.setdefault(e.pop("batch"), []).append(e)
    for n, events in sorted(batches.items()):
        path = f"{INPUT}/batch_{n}.json"
        with open(path, "w") as out:
            out.writelines(json.dumps(e) + "\n" for e in events)
        # Файловый источник берёт файлы по времени изменения, задаём его явно
        os.utime(path, (1_700_000_000 + n, 1_700_000_000 + n))
    return sum(len(v) for v in batches.values())


def run_query(spark, name, window_col):
    """Оконная агрегация по ключу user в режиме append и сводка по каждому микробатчу."""
    events = (spark.readStream.schema(SCHEMA)
              .option("maxFilesPerTrigger", 1)
              .json(INPUT))
    agg = (events
           .withWatermark("ts", WATERMARK)
           .groupBy("user", window_col.alias("w"))
           .agg(F.count("*").alias("cnt"),
                F.array_sort(F.collect_list("id")).alias("ids")))
    q = (agg.writeStream
         .format("memory").queryName(name)
         .outputMode("append")          # окно уходит в результат один раз, когда watermark прошёл его конец
         .option("checkpointLocation", f"{WORK}/chk_{name}")
         .trigger(availableNow=True)
         .start())
    q.awaitTermination()

    print(f"\n----- {name}: микробатчи -----")
    print("batch  вход  watermark_в_батче      окон_в_состоянии  выдано  отброшено_опоздавших")
    for p in q.recentProgress:
        st = p["stateOperators"][0] if p["stateOperators"] else {}
        wm = p.get("eventTime", {}).get("watermark", "-")
        print(f"{p['batchId']:>5}  {p['numInputRows']:>4}  {wm:<24} {st.get('numRowsTotal', '-'):>14}"
              f"  {p['sink'].get('numOutputRows', '-'):>6}"
              f"  {st.get('numRowsDroppedByWatermark', '-'):>20}")
    last = q.recentProgress[-1]["stateOperators"][0]
    print(f"после последнего батча: окон в состоянии {last['numRowsTotal']}, "
          f"память состояния {last['memoryUsedBytes']} байт")

    rows = spark.sql(f"select user, w.start as s, w.end as e, cnt, ids from {name} order by user, s").collect()
    print(f"\n----- {name}: закрытые окна (append) -----")
    for r in rows:
        print(f"{r.user}  [{r.s:%H:%M}, {r.e:%H:%M})  cnt={r.cnt}  {','.join(r.ids)}")
    total = sum(r.cnt for r in rows)
    print(f"окон выдано: {len(rows)}, сумма cnt по окнам: {total}")
    return len(rows), total, last["numRowsTotal"]


def main():
    n_events = prepare_input()
    spark = (SparkSession.builder.appName("windowing_demo")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", 2)
             .getOrCreate())
    print(f"pyspark {spark.version}, python {sys.version.split()[0]}")
    print(f"событий во входе: {n_events}; watermark {WATERMARK}; tumbling {SIZE}; "
          f"sliding {SIZE} с шагом {SLIDE}; session gap {GAP}")

    # Сколько окон получает каждое событие: статическое чтение тех же файлов
    static = spark.read.schema(SCHEMA).json(INPUT)
    print("\n----- сколько окон получает одно событие (статический DataFrame) -----")
    for name, col in [("tumbling", F.window("ts", SIZE)),
                      ("sliding", F.window("ts", SIZE, SLIDE))]:
        per_event = static.select("id", col.alias("w")).groupBy("id").count()
        dist = sorted((r["count"], r["n"]) for r in
                      per_event.groupBy("count").agg(F.count("*").alias("n")).collect())
        print(f"{name}: окон на событие -> событий {dist}")
    e01 = static.where("id = 'e01'").select(F.window("ts", SIZE, SLIDE).alias("w")).orderBy("w.start").collect()
    print("e01 12:01 в sliding-окнах:", ", ".join(f"[{r.w.start:%H:%M}, {r.w.end:%H:%M})" for r in e01))

    plan = static.groupBy("user", F.window("ts", SIZE, SLIDE)).count()._jdf.queryExecution().executedPlan().toString()
    print("в физическом плане sliding-агрегации:",
          [ln.strip().split("[")[0].lstrip("+- :") for ln in plan.splitlines() if "Expand" in ln])

    results = {}
    results["tumbling"] = run_query(spark, "tumbling", F.window("ts", SIZE))
    results["sliding"] = run_query(spark, "sliding", F.window("ts", SIZE, SLIDE))
    results["session"] = run_query(spark, "session", F.session_window("ts", GAP))

    print("\n----- сводка -----")
    print("тип        окон_выдано  сумма_cnt  окон_осталось_в_состоянии")
    for name, (n, total, left) in results.items():
        print(f"{name:<10} {n:>11}  {total:>9}  {left:>25}")
    spark.stop()


if __name__ == "__main__":
    main()
