from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.providers.apache.hdfs.hooks.webhdfs import WebHDFSHook
from datetime import datetime
import os

BUCKET_NAME = "airflow-course"
# Шаблоны оставляем здесь, но использовать их будем через параметры оператора
S3_KEY_TEMPLATE = "users_export_{{ ds }}.csv"
HDFS_PATH_TEMPLATE = "/user/airflow/backup/users_{{ ds }}.csv"

# 1. Добавляем аргументы s3_key и hdfs_dest в функцию
def transfer_s3_to_hdfs(s3_key, hdfs_dest, **kwargs):
    print(f"Обрабатываем файлы. Источник: {s3_key}, Назначение: {hdfs_dest}")
    
    # 1. Скачиваем файл из S3
    s3_hook = S3Hook(aws_conn_id="Yandex_s3")
    local_filename = s3_hook.download_file(
        key=s3_key,  # <--- ИСПОЛЬЗУЕМ АРГУМЕНТ, А НЕ ГЛОБАЛЬНУЮ ПЕРЕМЕННУЮ
        bucket_name=BUCKET_NAME,
        local_path="/tmp"
    )
    print(f"Файл скачан из S3: {local_filename}")

    # 2. Загружаем в HDFS
    hdfs_hook = WebHDFSHook(webhdfs_conn_id="my_hdfs_conn")
    
    hdfs_hook.load_file(
        source=local_filename,
        destination=hdfs_dest, # <--- И ЗДЕСЬ ТОЖЕ АРГУМЕНТ
        overwrite=True
    )
    print(f"Файл загружен в HDFS: {hdfs_dest}")

    # 3. Уборка
    # local_filename уже содержит полный путь, созданный хуком, удаляем его
    if os.path.exists(local_filename):
        os.remove(local_filename)

with DAG(
    dag_id="05.1.s3_to_hdfs_loader",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False
    ) as dag:

    wait_for_file = S3KeySensor(
        task_id="wait_for_s3_file",
        bucket_name=BUCKET_NAME,
        bucket_key=S3_KEY_TEMPLATE, # Здесь шаблонизация работает сама (поле templated)
        aws_conn_id="Yandex_s3",
        poke_interval=30,
        timeout=600,
        mode="reschedule"
    )

    move_data = PythonOperator(
        task_id="move_to_hdfs",
        python_callable=transfer_s3_to_hdfs,
        # Airflow "прожует" эти строки, подставит дату и передаст в функцию готовые значения
        op_kwargs={
            "s3_key": S3_KEY_TEMPLATE, 
            "hdfs_dest": HDFS_PATH_TEMPLATE,
        },
    )

    wait_for_file >> move_data
