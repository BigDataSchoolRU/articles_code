# openlineage-python 1.55.0 (спецификация 2-0-2), Python 3.12, SQLite из stdlib; прогнано на стенде 2026-11-12
"""Конвейер из двух заданий, который сам сообщает о своих запусках событиями OpenLineage.

load_orders_clean    data/orders.csv           -> staging.orders_clean  (оплаченные заказы)
build_daily_revenue  staging.orders_clean      -> mart.daily_revenue    (выручка по дням)

Работа настоящая: CSV читается, таблицы SQLite пишутся. Каждый запуск даёт событие START и
одно из COMPLETE или FAIL. Первый запуск второго задания падает на ошибке в SQL, второй проходит.

Режим broken шлёт ещё одно задание, которое называет тот же CSV относительным путём:
у события другой ключ датасета, и в графе потребителя появляется отдельный, несвязанный узел.
"""
import csv
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# клиент ищет openlineage.yml по переменной OPENLINEAGE_CONFIG, затем в текущем каталоге
os.environ.setdefault("OPENLINEAGE_CONFIG", str(HERE / "openlineage.yml"))
os.chdir(HERE)  # файловый транспорт пишет emitted.jsonl относительно текущего каталога

from openlineage.client import OpenLineageClient  # noqa: E402
from openlineage.client.event_v2 import InputDataset, Job, OutputDataset, Run, RunEvent, RunState  # noqa: E402
from openlineage.client.facet_v2 import (  # noqa: E402
    column_lineage_dataset as cl,
    error_message_run,
    job_type_job,
    schema_dataset,
    sql_job,
)
from openlineage.client.uuid import generate_new_uuid  # noqa: E402

PRODUCER = "https://github.com/BigDataSchoolRU/articles_code/tree/main/wiki/openlineage"
JOB_NS = "bds_demo"                       # пространство имён заданий
WH_NS = "sqlite://warehouse"              # пространство имён таблиц хранилища
SRC = HERE / "data" / "orders.csv"
WH = HERE / "warehouse"

client = OpenLineageClient()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def schema(*fields: tuple[str, str]) -> dict:
    return {"schema": schema_dataset.SchemaDatasetFacet(
        fields=[schema_dataset.SchemaDatasetFacetFields(name=n, type=t) for n, t in fields])}


def field(ns: str, name: str, col: str, ttype: str, subtype: str) -> cl.InputField:
    return cl.InputField(namespace=ns, name=name, field=col,
                         transformations=[cl.Transformation(type=ttype, subtype=subtype)])


def emit(state: RunState, run_id: str, job: Job, inputs: list, outputs: list, run_facets: dict | None = None) -> None:
    client.emit(RunEvent(eventType=state, eventTime=now(), run=Run(runId=run_id, facets=run_facets or {}),
                         job=job, inputs=inputs, outputs=outputs, producer=PRODUCER))
    print(f"  -> {state.value:<8} {job.namespace}/{job.name} run=…{run_id[-12:]}")


def connect() -> sqlite3.Connection:
    WH.mkdir(exist_ok=True)
    con = sqlite3.connect(":memory:")
    # схемы staging и mart это отдельные файлы базы, подключённые под своими именами
    con.execute(f"ATTACH '{WH / 'staging.db'}' AS staging")
    con.execute(f"ATTACH '{WH / 'mart.db'}' AS mart")
    return con


def load_orders_clean(con: sqlite3.Connection) -> None:
    print("load_orders_clean")
    job = Job(namespace=JOB_NS, name="load_orders_clean", facets={
        "jobType": job_type_job.JobTypeJobFacet(processingType="BATCH", integration="PYTHON", jobType="TASK")})
    # ключ датасета для локального файла: namespace "file" и абсолютный путь, так же называет его Spark
    src = InputDataset(namespace="file", name=str(SRC), facets=schema(
        ("order_id", "integer"), ("customer", "string"), ("order_ts", "string"), ("amount", "decimal"), ("status", "string")))
    run_id = str(generate_new_uuid())
    emit(RunState.START, run_id, job, [src], [])

    with SRC.open(encoding="utf-8") as f:
        rows = [(int(r["order_id"]), r["customer"], r["order_ts"][:10], float(r["amount"]))
                for r in csv.DictReader(f) if r["status"] == "paid"]
    con.execute("DROP TABLE IF EXISTS staging.orders_clean")
    con.execute("CREATE TABLE staging.orders_clean (order_id INTEGER, customer TEXT, order_date TEXT, amount REAL)")
    con.executemany("INSERT INTO staging.orders_clean VALUES (?, ?, ?, ?)", rows)
    con.commit()
    print(f"  записано строк: {len(rows)} (оплаченные из {sum(1 for _ in SRC.open()) - 1})")

    s = str(SRC)
    out = OutputDataset(namespace=WH_NS, name="staging.orders_clean", facets={
        **schema(("order_id", "INTEGER"), ("customer", "TEXT"), ("order_date", "TEXT"), ("amount", "REAL")),
        "columnLineage": cl.ColumnLineageDatasetFacet(
            fields={
                "order_id": cl.Fields(inputFields=[field("file", s, "order_id", "DIRECT", "IDENTITY")]),
                "customer": cl.Fields(inputFields=[field("file", s, "customer", "DIRECT", "IDENTITY")]),
                "order_date": cl.Fields(inputFields=[field("file", s, "order_ts", "DIRECT", "TRANSFORMATION")]),
                "amount": cl.Fields(inputFields=[field("file", s, "amount", "DIRECT", "IDENTITY")]),
            },
            # фильтр по статусу влияет на весь датасет, а не на одно поле
            dataset=[field("file", s, "status", "INDIRECT", "FILTER")]),
    })
    emit(RunState.COMPLETE, run_id, job, [src], [out])


DAILY_SQL = """INSERT INTO mart.daily_revenue
SELECT order_date AS day, count(order_id) AS orders, round(sum({amount}), 2) AS revenue
FROM staging.orders_clean GROUP BY order_date"""


def build_daily_revenue(con: sqlite3.Connection, amount_col: str) -> bool:
    print(f"build_daily_revenue (колонка суммы: {amount_col})")
    sql = DAILY_SQL.format(amount=amount_col)
    job = Job(namespace=JOB_NS, name="build_daily_revenue", facets={
        "sql": sql_job.SQLJobFacet(query=sql, dialect="sqlite"),
        "jobType": job_type_job.JobTypeJobFacet(processingType="BATCH", integration="PYTHON", jobType="TASK")})
    src = InputDataset(namespace=WH_NS, name="staging.orders_clean")
    run_id = str(generate_new_uuid())
    emit(RunState.START, run_id, job, [src], [])
    try:
        con.execute("DROP TABLE IF EXISTS mart.daily_revenue")
        con.execute("CREATE TABLE mart.daily_revenue (day TEXT, orders INTEGER, revenue REAL)")
        con.execute(sql)
        con.commit()
    except sqlite3.Error as e:
        con.rollback()
        print(f"  задание упало: {type(e).__name__}: {e}")
        # ошибка уходит фасетом запуска, потребитель видит её рядом с графом
        emit(RunState.FAIL, run_id, job, [src], [], run_facets={
            "errorMessage": error_message_run.ErrorMessageRunFacet(
                message=f"{type(e).__name__}: {e}", programmingLanguage="PYTHON",
                stackTrace=traceback.format_exc(limit=1))})
        return False

    t = "staging.orders_clean"
    out = OutputDataset(namespace=WH_NS, name="mart.daily_revenue", facets={
        **schema(("day", "TEXT"), ("orders", "INTEGER"), ("revenue", "REAL")),
        "columnLineage": cl.ColumnLineageDatasetFacet(
            fields={
                "day": cl.Fields(inputFields=[field(WH_NS, t, "order_date", "DIRECT", "IDENTITY")]),
                "orders": cl.Fields(inputFields=[field(WH_NS, t, "order_id", "DIRECT", "AGGREGATION")]),
                "revenue": cl.Fields(inputFields=[field(WH_NS, t, "amount", "DIRECT", "AGGREGATION")]),
            },
            dataset=[field(WH_NS, t, "order_date", "INDIRECT", "GROUP_BY")]),
    })
    emit(RunState.COMPLETE, run_id, job, [src], [out])
    for row in con.execute("SELECT * FROM mart.daily_revenue ORDER BY day"):
        print("  ", row)
    return True


def broken() -> None:
    # Та же самая таблица-источник, но названа относительным путём: другой ключ датасета.
    print("orders_report (CSV назван относительным путём)")
    job = Job(namespace=JOB_NS, name="orders_report")
    src = InputDataset(namespace="file", name="data/orders.csv")
    out = OutputDataset(namespace="file", name=str(HERE / "report.txt"))
    run_id = str(generate_new_uuid())
    emit(RunState.START, run_id, job, [src], [])
    (HERE / "report.txt").write_text(f"заказов в файле: {sum(1 for _ in SRC.open()) - 1}\n", encoding="utf-8")
    emit(RunState.COMPLETE, run_id, job, [src], [out])


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pipeline"
    if mode == "broken":
        broken()
        return 0
    con = connect()
    load_orders_clean(con)
    build_daily_revenue(con, amount_col="amount_rub")        # ошибка в имени колонки
    ok = build_daily_revenue(con, amount_col="amount")       # исправленный запуск
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
