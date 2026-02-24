import json
import logging
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.apache.kafka.sensors.kafka import AwaitMessageSensor

# --- Constants ---
KAFKA_TOPIC = "etl_start"
KAFKA_CONN_ID = "kafka_default"
POLL_INTERVAL = 10       # seconds between polls
POLL_TIMEOUT = 3600      # max wait time in seconds (1 hour)
TRIGGER_STATUS = "ready"

DEFAULT_ARGS = {
    "owner": "data-team",
    "retries": 1,
}


def check_event(message) -> dict | None:
    """
    Called by AwaitMessageSensor for every incoming Kafka message.
    Returns the parsed payload when status == TRIGGER_STATUS, otherwise None
    (which tells the sensor to keep waiting).
    """
    try:
        raw = message.value().decode("utf-8")
        data: dict = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logging.warning("Skipping unreadable message: %s", e)
        return None

    if data.get("status") == TRIGGER_STATUS:
        logging.info("Trigger received, stopping sensor wait. Payload: %s", data)
        return data

    logging.debug("Ignoring message with status=%r", data.get("status"))
    return None


def process_data(**kwargs) -> None:
    """
    Downstream task that consumes the Kafka payload captured by the sensor.
    Pulls the trigger payload from XCom and uses it to drive processing.
    """
    ti = kwargs["ti"]
    payload: dict | None = ti.xcom_pull(task_ids="wait_for_kafka_msg")

    if not payload:
        logging.warning("No payload received from sensor — skipping processing")
        return

    logging.info("Processing triggered by Kafka event. Payload: %s", payload)
    # TODO: replace with real ETL logic using payload fields
    logging.info("Simulating heavy data export …")


with DAG(
    dag_id="08.kafka_event_driven",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["kafka"],
) as dag:

    wait_for_event = AwaitMessageSensor(
        task_id="wait_for_kafka_msg",
        kafka_config_id=KAFKA_CONN_ID,
        topics=[KAFKA_TOPIC],
        apply_function="08_kafka_event_driven.check_event",
        poll_interval=POLL_INTERVAL,
        poll_timeout=POLL_TIMEOUT,
    )

    run_job = PythonOperator(
        task_id="process_data",
        python_callable=process_data,
    )

    wait_for_event >> run_job
