# apache-airflow 3.3.2, apache-airflow-providers-clickhousedb 1.0.1, ClickHouse 26.9.23.15, прогнано на стенде 2026-10-21
"""Ретрай задачи после успешной вставки: где ClickHouse отбросит повтор, а где задвоит строки."""
from datetime import datetime, timedelta

from airflow.providers.clickhousedb.hooks.clickhouse import ClickHouseHook
from airflow.sdk import dag, get_current_context, task

ROWS = 1000
COLUMNS = ["id", "event", "loaded_at"]
WINDOW = "SETTINGS non_replicated_deduplication_window = 1000"

SYNC = {"async_insert": 0}  # в ClickHouse 26.9 async_insert включён по умолчанию

# таблица -> (настройки MergeTree, токен: False / True / "per_batch", доп. настройки сессии, batch_size)
CASES = {
    "events_no_window": ("", True, SYNC, None),                 # токен есть, окна нет
    "events_no_token": (WINDOW, False, SYNC, None),             # окно есть, токена нет
    "events_token_sync": (WINDOW, True, SYNC, None),            # окно и токен, синхронная вставка
    "events_token_batches": (WINDOW, True, SYNC, 500),          # один токен на все пачки
    "events_token_per_batch": (WINDOW, "per_batch", SYNC, 500), # свой токен у каждой пачки
    "events_token_async": (WINDOW, True, {}, None),             # окно и токен, дефолты сервера
    "events_token_async_dedup": (WINDOW, True, {"async_insert_deduplicate": 1}, None),
}


def make_rows():
    # loaded_at меняется от попытки к попытке, поэтому хеш блока у повтора другой
    loaded_at = datetime.now()
    return [(i, f"click_{i % 5}", loaded_at) for i in range(ROWS)]


@dag(schedule=None, start_date=datetime(2026, 10, 1), catchup=False, tags=["clickhouse"])
def retry_dedup():
    @task
    def prepare():
        hook = ClickHouseHook()
        for table, (mt_settings, *_rest) in CASES.items():
            hook.run(
                f"CREATE OR REPLACE TABLE {table} "
                f"(id UInt32, event String, loaded_at DateTime64(6)) "
                f"ENGINE = MergeTree ORDER BY id {mt_settings}"
            )

    @task(retries=1, retry_delay=timedelta(seconds=5))
    def load(table: str):
        _, use_token, extra, batch_size = CASES[table]
        ctx = get_current_context()
        ti = ctx["ti"]
        settings = dict(extra)
        # токен детерминирован: одинаков у первой попытки и у ретрая
        token = f"{ti.dag_id}:{ctx['run_id']}:{ti.task_id}"
        rows = make_rows()
        if use_token == "per_batch":
            # bulk_insert_rows не умеет менять настройки между пачками, поэтому клиент напрямую
            hook = ClickHouseHook(session_settings=settings)
            client = hook.get_client()
            try:
                for n, start in enumerate(range(0, len(rows), batch_size)):
                    client.insert(
                        table,
                        rows[start : start + batch_size],
                        column_names=COLUMNS,
                        settings={"insert_deduplication_token": f"{token}:batch{n}"},
                    )
            finally:
                client.close()
        else:
            if use_token:
                settings["insert_deduplication_token"] = token
            # параметра settings у bulk_insert_rows нет, токен едет через session_settings хука
            hook = ClickHouseHook(session_settings=settings)
            hook.bulk_insert_rows(table, rows, COLUMNS, batch_size=batch_size)
        if ti.try_number == 1:
            raise RuntimeError("сбой после вставки: строки уже в ClickHouse, задача уходит в ретрай")

    @task(trigger_rule="all_done")
    def report():
        hook = ClickHouseHook()
        for table in CASES:
            rows = hook.get_first(f"SELECT count() FROM {table}")[0]
            print(f"{table}: {rows} строк при ожидаемых {ROWS}")

    loads = [load.override(task_id=f"load_{table}")(table) for table in CASES]
    prepare() >> loads >> report()


retry_dedup()
