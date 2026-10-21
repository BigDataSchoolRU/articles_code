# apache/airflow 3.3.2 + провайдер clickhousedb 1.0.1 и airflow-clickhouse-plugin 1.8.0, прогнано на стенде 2026-10-21
FROM apache/airflow:3.3.2-python3.12
COPY requirements.txt /requirements.txt
# пин самого Airflow, чтобы pip не обновил его вместе с провайдерами
RUN pip install --no-cache-dir "apache-airflow==3.3.2" -r /requirements.txt
