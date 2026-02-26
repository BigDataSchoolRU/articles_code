"""
DAG: проверка flag.txt в S3 → выгрузка Postgres в S3.
Сначала проверяем наличие flag.txt в бакете; если нет — падаем.
Затем выгружаем users из Postgres в CSV и загружаем в S3.
"""

import csv
import os
from datetime import datetime

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.providers.postgres.hooks.postgres import PostgresHook

# Бакет (должен быть создан заранее)
BUCKET_NAME = "airflow-bucket"
# Имя файла в S3 с датой запуска
KEY_NAME = "users_export_{{ ds }}.csv"
S3_CONN_ID = "yandex_s3"


def check_flag_file(**context):
    """
    Проверяет наличие flag.txt в бакете через S3Hook.
    Падает с AirflowException, если файла нет.
    """
    hook = S3Hook(aws_conn_id=S3_CONN_ID)
    key = "flag.txt"

    if not hook.check_for_key(key=key, bucket_name=BUCKET_NAME):
        raise AirflowException(
            f"Файл '{key}' не найден в бакете '{BUCKET_NAME}'. "
            "Дальнейшее выполнение невозможно."
        )

    return f"Файл '{key}' найден в бакете '{BUCKET_NAME}', продолжаем."


def export_postgres_to_s3(ds, **kwargs):
    """
    Выгружает users из Postgres в CSV и загружает в S3.
    """
    # 1. Забираем данные из Postgres
    pg_hook = PostgresHook(postgres_conn_id="my_dwh")
    connection = pg_hook.get_conn()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users")
    results = cursor.fetchall()

    # 2. Сохраняем во временный локальный файл
    local_filename = f"/tmp/users_{ds}.csv"

    with open(local_filename, "w") as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(["id", "name", "date"])
        csv_writer.writerows(results)

    print(f"Данные выгружены локально: {local_filename}")

    # 3. Загружаем в S3
    s3_hook = S3Hook(aws_conn_id=S3_CONN_ID)
    key_name = f"users_export_{ds}.csv"

    s3_hook.load_file(
        filename=local_filename,
        key=key_name,
        bucket_name=BUCKET_NAME,
        replace=True,
    )

    print(f"Файл успешно загружен в S3: {BUCKET_NAME}/{key_name}")

    # 4. Удаляем локальный файл
    os.remove(local_filename)


with DAG(
    dag_id="post_new_s3",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["postgres", "s3", "yandex"],
) as dag:

    check_flag = PythonOperator(
        task_id="check_flag_exists",
        python_callable=check_flag_file,
    )

    upload_to_s3 = PythonOperator(
        task_id="upload_to_s3",
        python_callable=export_postgres_to_s3,
    )

    check_flag >> upload_to_s3
