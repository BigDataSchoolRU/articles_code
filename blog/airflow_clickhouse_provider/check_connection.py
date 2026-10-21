# apache-airflow-providers-clickhousedb 1.0.1, clickhouse-connect 1.11.0, ClickHouse 26.9.23.15, прогнано на стенде 2026-10-21
# Запуск внутри контейнера Airflow: соединение clickhouse_default берётся из AIRFLOW_CONN_CLICKHOUSE_DEFAULT
from airflow.providers.clickhousedb.hooks.clickhouse import ClickHouseHook

hook = ClickHouseHook()  # clickhouse_conn_id по умолчанию clickhouse_default

# test_connection() из DbApiHook выполняет SELECT 1 через DB-API адаптер провайдера
print("test_connection:", hook.test_connection())

# get_records идёт через курсор clickhouse_connect.dbapi, как в SQLExecuteQueryOperator
print("версия сервера:", hook.get_records("SELECT version()")[0][0])

# дефолты сервера, от которых зависит дедупликация вставок
print("настройки сессии:")
for name, value, changed in hook.get_records(
    "SELECT name, value, changed FROM system.settings WHERE name IN "
    "('async_insert', 'wait_for_async_insert', 'async_insert_deduplicate', "
    "'insert_deduplicate', 'insert_deduplication_token') ORDER BY name"
):
    print(f"  {name} = {value!r} (changed={changed})")

print("настройки MergeTree:")
for name, value in hook.get_records(
    "SELECT name, value FROM system.merge_tree_settings "
    "WHERE name IN ('non_replicated_deduplication_window', 'replicated_deduplication_window') ORDER BY name"
):
    print(f"  {name} = {value}")

# session_settings хука уходят с каждым запросом клиента
tuned = ClickHouseHook(session_settings={"max_threads": 2})
print("max_threads с session_settings:", tuned.get_records("SELECT getSetting('max_threads')")[0][0])

# провайдер подписывает запросы версиями Airflow и своей в User-Agent, это видно в query_log
client = hook.get_client()
client.command("SYSTEM FLUSH LOGS")
ua = client.query(
    "SELECT http_user_agent FROM system.query_log "
    "WHERE http_user_agent LIKE 'apache-airflow%' ORDER BY event_time_microseconds DESC LIMIT 1"
).result_rows
client.close()
print("http_user_agent:", ua[0][0] if ua else "нет записи")
