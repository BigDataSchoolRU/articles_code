import json
import logging
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.apache.kafka.sensors.kafka import AwaitMessageSensor
from datetime import datetime

# Функция для фонового процесса (триггера)
def check_event(message):
    try:
        val = message.value().decode('utf-8')
        data = json.loads(val)
        
        if data.get("status") == "ready":
            logging.info("Сигнал получен, завершаем ожидание")
            return data 
            
    except Exception as e:
        logging.warning(f"Неизвестный формат сообщения, пропускаем: {e}")
        
    # Явный возврат пустоты заставляет сенсор ждать следующее сообщение
    return None 

def process_data():
    logging.info("Имитация тяжелой выгрузки данных")

with DAG(
    dag_id="08.kafka_event_driven",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False,
    tags=['kafka']
) as dag:
    
    wait_for_event = AwaitMessageSensor(
        task_id="wait_for_kafka_msg",
        kafka_config_id="kafka_default", 
        topics=["etl_start"],
        apply_function="08_kafka_event_driven.check_event", 
        poll_interval=10,
        poll_timeout=3600,
    )

    run_job = PythonOperator(
        task_id="process_data",
        python_callable=process_data
    )

    wait_for_event >> run_job
