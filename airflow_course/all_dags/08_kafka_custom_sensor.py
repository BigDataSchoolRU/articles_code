import json
import logging
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.apache.kafka.sensors.produce_consume import AwaitMessageTriggerFunctionSensor
from datetime import datetime

# Функция-обработчик. Airflow будет передавать в нее каждое новое сообщение из топика.
# Важно: она должна лежать на уровне модуля, чтобы Airflow мог ее сериализовать.
def check_event(message):
    try:
        # message - это объект confluent_kafka.Message
        val = message.value().decode('utf-8')
        data = json.loads(val)
        
        if data.get("status") == "ready":
            logging.info("Отмашка получена, запускаем обработку.")
            return True # Возвращаем True, сенсор успешно завершает работу
            
    except Exception as e:
        logging.warning(f"Пришло сообщение в другом формате, игнорируем: {e}")
        
    return False # Возвращаем False, сенсор продолжает слушать эфир

def process_data():
    logging.info("Имитация тяжелой обработки данных...")

with DAG(
    dag_id="08.kafka_event_driven",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False
) as dag:
    
    wait_for_event = AwaitMessageTriggerFunctionSensor(
        task_id="wait_for_kafka_msg",
        kafka_config_id="kafka_default", # Ссылка на подключение в Airflow
        topics=["etl_start"],
        # Здесь указываем путь к нашей функции проверки. 
        # Если файл называется 08_kafka_event_driven.py, то путь такой:
        apply_function="08_kafka_event_driven.check_event", 
        poll_interval=10,
        poll_timeout=3600,
    )

    run_job = PythonOperator(
        task_id="process_data",
        python_callable=process_data
    )

    wait_for_event >> run_job
