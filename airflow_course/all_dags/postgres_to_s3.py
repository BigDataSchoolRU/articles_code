from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from datetime import datetime
import csv
import os

# Название бакета (должен быть создан заранее!)
BUCKET_NAME = "airflow-course" 
# Имя файла с датой запуска
KEY_NAME = "users_export_{{ ds }}.csv"

def export_postgres_to_s3(ds, **kwargs):
    # 1. Забираем данные из Postgres
    pg_hook = PostgresHook(postgres_conn_id="my_dwh")
    connection = pg_hook.get_conn()
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users")
    results = cursor.fetchall()
    
    # 2. Сохраняем во временный локальный файл
    # Важно: /tmp/ очищается, не засоряя диск
    local_filename = f"/tmp/users_{ds}.csv"
    
    with open(local_filename, 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(['id', 'name', 'date']) # Заголовки
        csv_writer.writerows(results)
    
    print(f"Данные выгружены локально: {local_filename}")

    # 3. Загружаем в S3 (MinIO или Yandex)
    # Используем conn_id, который мы настроили (minio_s3 или yandex_s3)
    s3_hook = S3Hook(aws_conn_id="Yandex_s3") 
    
    s3_hook.load_file(
        filename=local_filename,
        key=KEY_NAME,         # Имя файла в облаке
        bucket_name=BUCKET_NAME,
        replace=True          # Перезаписывать, если файл уже есть (Идемпотентность!)
    )
    
    print(f"Файл успешно загружен в S3: {BUCKET_NAME}/{KEY_NAME}")
    
    # 4. Убираем за собой (удаляем локальный файл)
    os.remove(local_filename)

with DAG(
    dag_id="04.export_to_datalake",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False
) as dag:

    upload_task = PythonOperator(
        task_id="upload_to_s3",
        python_callable=export_postgres_to_s3
    )

