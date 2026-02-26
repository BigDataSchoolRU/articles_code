from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from datetime import datetime

# Путь к HDFS, куда мы писали в прошлой статье
# Обратите внимание: spark внутри Docker-сети может обращаться к namenode
HDFS_INPUT = "hdfs://namenode:8020/user/airflow/backup/users_{{ ds }}.csv"
HDFS_OUTPUT = "hdfs://namenode:8020/user/airflow/reports/daily_{{ ds }}"

with DAG(
    dag_id="06.spark_processing",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False
) as dag:

    process_task = SparkSubmitOperator(
        task_id="run_spark_job",
        conn_id="my_spark_conn",
 # Путь к скрипту внутри контейнера AIRFLOW
        application="/opt/airflow/jobs/user_analytics.py", 
        
        # Аргументы для скрипта (input и output)
        application_args=[HDFS_INPUT, HDFS_OUTPUT],
        
        # Конфигурация ресурсов (сколько отдать Спарку)
        conf={
            "spark.driver.memory": "512m",
            "spark.executor.memory": "512m"
        },
        
        # Важно! Указываем пакеты, если нужно работать с S3 или другими системами
        # packages="org.apache.hadoop:hadoop-aws:3.2.0",
        
        verbose=True
    )

