from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import datetime
from dask.distributed import Client, wait
import logging

# Настройки бакета
BUCKET_NAME = "airflow-course"  # Ваш бакет
S3_FILE_PATTERN = "users_export_*.csv" # Маска файлов, которые загружали ранее

def offload_to_dask():
    logging.info("Инициализация подключения к Dask Cluster...")
    
    # 1. Подключаемся к планировщику (имя сервиса из docker-compose)
    client = Client("tcp://dask-scheduler:8786")
    logging.info(f"Подключение успешно: {client}")

    # 2. Функция обработки, которая полетит на кластер
    # ВАЖНО: Внутри функции нужно импортировать библиотеки заново, 
    # так как она выполняется в другом процессе/контейнере
    def heavy_processing_task(bucket, pattern, aws_key, aws_secret):
        import dask.dataframe as dd
        
        # Настройки для Yandex Object Storage (передаем в s3fs)
        storage_opts = {
            "key": aws_key,
            "secret": aws_secret,
            "client_kwargs": {
                "endpoint_url": "https://storage.yandexcloud.net",
                "region_name": "ru-central1",
            },
            "config_kwargs": {
              "s3": {"addressing_style": "path"}
              },
        }
        
        # Читаем CSV прямо из S3 (ленивое чтение)
        s3_path = f"s3://{bucket}/{pattern}"
        ddf = dd.read_csv(s3_path, storage_options=storage_opts)
        
        # Пример тяжелой операции: группировка и подсчет
        # .compute() запускает реальные вычисления на воркере
        # result = ddf.groupby('date').size().compute()
        expr = ddf.groupby("date").size()
        future = client.compute(expr)
        result = future.result()
        
        # Сохраняем результат обратно в S3 (в формате CSV для наглядности)
        #output_path = f"s3://{bucket}/dask_results/report.csv"
        fs = s3fs.S3FileSystem(
        key=aws_key,
        secret=aws_secret,
        client_kwargs={"endpoint_url": endpoint, "region_name": region},
        config_kwargs={"s3": {"addressing_style": "path"}},
    )

    out_key = f"{BUCKET_NAME}/dask_results/report.csv"
    result = result.rename("count")
    with fs.open(out_key, "w") as f:
        result.to_csv(f)

    client.close()
    return result.to_dict()

        # Превращаем результат (Pandas Series) обратно в Dask DataFrame для записи
        dd.from_pandas(result, npartitions=1).to_csv(
            output_path, 
            storage_options=storage_opts,
            single_file=True
        )
        
        return output_path

    # 3. Получаем креды Яндекса (лучше брать из Airflow Connections, но для простоты - Variables или хардкод)
    # Предполагаем, что вы создали Variable в Admin -> Variables c именем 'yandex_creds'
    # В формате JSON: {"key": "...", "secret": "..."}
    # ИЛИ (для теста) впишите свои ключи ниже, если не хотите возиться с Variables
    # aws_key = "ВАШ_ACCESS_KEY"
    # aws_secret = "ВАШ_SECRET_KEY"
    
    # Чтобы не светить ключи в коде, попробуем достать из Environment (если прокинули в docker-compose)
    import os
    aws_key = os.getenv("AWS_ACCESS_KEY_ID", "ЗАМЕНИТЕ_НА_КЛЮЧ_ЕСЛИ_НЕТ_ENV")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "ЗАМЕНИТЕ_НА_СЕКРЕТ_ЕСЛИ_НЕТ_ENV")

    # 4. Отправляем задачу на кластер
    future = client.submit(heavy_processing_task, BUCKET_NAME, S3_FILE_PATTERN, aws_key, aws_secret)
    
    logging.info("Задача отправлена в Dask. Ждем...")
    
    # Ждем завершения
    wait(future)
    
    # Получаем результат (путь к файлу)
    try:
        result_path = future.result()
        logging.info(f"Успех! Данные сохранены в: {result_path}")
    except Exception as e:
        logging.error(f"Ошибка вычислений в Dask: {e}")
        raise e
        
    client.close()

with DAG(
    dag_id="07.dask_yandex_processing",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False,
    tags=['dask', 'yandex']
) as dag:

    run_on_dask = PythonOperator(
        task_id="run_on_dask_cluster",
        python_callable=offload_to_dask
    )
