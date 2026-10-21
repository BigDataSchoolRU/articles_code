# apache-airflow-providers-clickhousedb 1.0.1, airflow-clickhouse-plugin 1.8.0, clickhouse-connect 1.11.0, ClickHouse 26.9.23.15, прогнано на стенде 2026-10-21
# Замер путей вставки. Запуск внутри контейнера Airflow: соединения берутся из AIRFLOW_CONN_*
import statistics
import time
from datetime import datetime, timedelta

from airflow.providers.clickhousedb.hooks.clickhouse import ClickHouseHook
from airflow_clickhouse_plugin.hooks.clickhouse import ClickHouseHook as PluginHook

N = 1_000_000          # строк для пакетных путей
N_ROWWISE = 2_000      # построчный insert_rows на миллионе не дождаться
REPEATS = 3
COLUMNS = ["id", "ts", "user_id", "event", "amount"]
TABLE = "bench_events"

base = datetime(2026, 10, 1)
ROWS = [(i, base + timedelta(seconds=i), i % 50_000, f"event_{i % 20}", i * 0.01) for i in range(N)]

admin = ClickHouseHook()
admin.run(
    f"CREATE OR REPLACE TABLE {TABLE} (id UInt64, ts DateTime, user_id UInt32, "
    f"event LowCardinality(String), amount Float64) ENGINE = MergeTree ORDER BY (event, ts)"
)


def bulk_default(rows):
    # дефолты сервера 26.9: async_insert=1, wait_for_async_insert=1
    ClickHouseHook().bulk_insert_rows(TABLE, rows, COLUMNS)


def bulk_sync(rows):
    ClickHouseHook(session_settings={"async_insert": 0}).bulk_insert_rows(TABLE, rows, COLUMNS)


def bulk_sync_batches(rows):
    # один insert context на все пачки, память ограничена размером пачки
    ClickHouseHook(session_settings={"async_insert": 0}).bulk_insert_rows(TABLE, rows, COLUMNS, batch_size=100_000)


def plugin_native(rows):
    # clickhouse-driver, нативный протокол 9000, settings передаются прямо в execute
    PluginHook(clickhouse_conn_id="clickhouse_native").execute(
        f"INSERT INTO {TABLE} VALUES", rows, settings={"async_insert": 0}
    )


def dbapi_rowwise(settings, executemany=False):
    # общий insert_rows из common-sql: курсор DB-API, INSERT на каждую строку
    def run(rows):
        ClickHouseHook(session_settings=settings).insert_rows(
            TABLE, rows, COLUMNS, commit_every=1000, executemany=executemany
        )
    return run


def measure(name, fn, rows, repeats):
    times = []
    for _ in range(repeats):
        admin.run(f"TRUNCATE TABLE {TABLE}")
        t = time.perf_counter()
        fn(rows)
        times.append(time.perf_counter() - t)
        got = admin.get_first(f"SELECT count() FROM {TABLE}")[0]
        assert got == len(rows), f"{name}: {got} строк вместо {len(rows)}"
    med = statistics.median(times)
    print(f"{name:<40} {len(rows):>9} строк  медиана {med:8.2f} с  {len(rows) / med:>12,.0f} строк/с")


print(f"{'путь':<40} {'объём':>9}        {'время':>14}  {'скорость':>15}")
measure("bulk_insert_rows, дефолты сервера", bulk_default, ROWS, REPEATS)
measure("bulk_insert_rows, async_insert=0", bulk_sync, ROWS, REPEATS)
measure("bulk_insert_rows, batch_size=100000", bulk_sync_batches, ROWS, REPEATS)
measure("airflow-clickhouse-plugin, native", plugin_native, ROWS, REPEATS)
measure("insert_rows (DB-API), дефолты сервера", dbapi_rowwise({}), ROWS[:N_ROWWISE], 1)
measure("insert_rows (DB-API), async_insert=0", dbapi_rowwise({"async_insert": 0}), ROWS[:N_ROWWISE], 1)
measure("insert_rows executemany, async_insert=0", dbapi_rowwise({"async_insert": 0}, True), ROWS[:N_ROWWISE], 1)
