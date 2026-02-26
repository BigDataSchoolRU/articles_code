from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.providers.apache.hdfs.hooks.webhdfs import WebHDFSHook
from datetime import datetime
import os

# Константы из прошлой статьи
BUCKET_NAME = "airflow-course"
S3_KEY_TEMPLATE = "users_export_{{ ds }}.csv"
HDFS_PATH_TEMPLATE = "/user/airflow/backup/users_{{ ds }}.csv"

def transfer_s3_to_hdfs(ds, **kwargs):
    # 1. Скачиваем файл из S3 (MinIO)
    s3_hook = S3Hook(aws_conn_id="Yandex_s3")
    local_filename = s3_hook.download_file(
        key=S3_KEY_TEMPLATE,
        bucket_name=BUCKET_NAME,
        local_path="/tmp"
    )
    print(f"Файл скачан из S3: {local_filename}")

    # 2. Загружаем в HDFS
    hdfs_hook = WebHDFSHook(webhdfs_conn_id="my_hdfs_conn")
    
    # Загружаем файл. Метод load_file сам создаст директорию, если её нет? 
    # Нет, WebHDFS капризен, лучше убедиться, что путь существует, или использовать метод, который это умеет.
    # В базовом WebHDFSHook load_file просто кладет данные.
    
    hdfs_dest = HDFS_PATH_TEMPLATE
    hdfs_hook.load_file(
        source=local_filename,
        destination=hdfs_dest,
        overwrite=True
    )
    print(f"Файл загружен в HDFS: {hdfs_dest}")

    # 3. Уборка
    os.remove(local_filename)

with DAG(
    dag_id="05.s3_to_hdfs_loader",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False
    ) as dag:

    # Шаг 1: Сенсор. Ждем, пока файл появится в бакете.
    wait_for_file = S3KeySensor(
        task_id="wait_for_s3_file",
        bucket_name=BUCKET_NAME,
        bucket_key=S3_KEY_TEMPLATE,
        aws_conn_id="Yandex_s3",
        poke_interval=30,  # Проверять каждые 30 секунд
        timeout=600,       # Если файла нет 10 минут - падать
        mode="reschedule"  # Важно! Освобождать воркер между проверками
    )

    # Шаг 2: Переливка данных
    move_data = PythonOperator(
        task_id="move_to_hdfs",
        python_callable=transfer_s3_to_hdfs,
        op_kwargs={
        "s3_key": "users_export_{{ ds }}.csv",
        "hdfs_dest": "/user/airflow/backup/users_{{ ds }}.csv",
    },
    )

    wait_for_file >> move_data

