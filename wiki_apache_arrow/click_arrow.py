import pyarrow as pa
import clickhouse_connect

# Подключение к БД
client = clickhouse_connect.get_client(host='localhost', username='default', password='P@ssw0rd1234')

# Подготовка таблицы Arrow
# Это может быть результат работы PySpark или чтения Parquet
data_table = pa.Table.from_pydict({
    'id': [1, 2, 3],
    'event_time': ['2023-10-01', '2023-10-02', '2023-10-03'],
    'value': [100, 200, 150]
})

# Вставка данных напрямую в формате Arrow
# ClickHouse читает поток байтов Arrow без лишнего парсинга текста
client.insert_arrow('my_analytics_table', data_table)
