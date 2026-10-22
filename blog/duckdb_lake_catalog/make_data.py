# duckdb 2.0.0, SeaweedFS 4.48 как S3, прогнано на стенде 2026-10-22
"""Синтетические события в S3 с Hive-разбиением: s3://lake/raw/events/dt=YYYY-MM-DD/.

Запуск: python make_data.py 2026-10-01 10 [--with-channel]
"""
import sys
from datetime import date, timedelta

import duckdb

ROWS_PER_DAY = 200_000
start = date.fromisoformat(sys.argv[1])
days = int(sys.argv[2])
# новая колонка в новых файлах: так выглядит эволюция схемы в сыром озере
with_channel = "--with-channel" in sys.argv

con = duckdb.connect()
con.execute("""
    CREATE SECRET s3 (TYPE s3, KEY_ID 'admin', SECRET 'password123',
        ENDPOINT '127.0.0.1:8333', URL_STYLE 'path', USE_SSL false, REGION 'us-east-1')
""")

for n in range(days):
    day = start + timedelta(days=n)
    channel = ", ['web', 'ios', 'android'][i % 3 + 1] AS channel" if with_channel else ""
    # детерминированные данные: одинаковый результат при каждом прогоне
    con.execute(f"""
        COPY (
            SELECT i AS event_id,
                   (hash(i, '{day}') % 50000)::BIGINT AS user_id,
                   ['DE', 'FR', 'PL', 'NL', 'ES', 'IT', 'SE'][i % 7 + 1] AS country,
                   round((hash(i * 7, '{day}') % 100000) / 100, 2) AS amount
                   {channel}
            FROM range({ROWS_PER_DAY}) t(i)
        ) TO 's3://lake/raw/events/dt={day}/data_0.parquet' (FORMAT parquet)
    """)
    print(f"dt={day}: {ROWS_PER_DAY} строк" + (" + колонка channel" if with_channel else ""))

files, size = con.sql("""
    SELECT count(*), sum(size) FROM read_blob('s3://lake/raw/events/*/*.parquet')
""").fetchall()[0]
print(f"всего в s3://lake/raw/events/: {files} файлов, {size / 1024 / 1024:.1f} МБ")
