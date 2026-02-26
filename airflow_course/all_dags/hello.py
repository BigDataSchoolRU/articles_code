from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime

with DAG(
    dag_id="hello_localexecutor",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
) as dag:
    t1 = BashOperator(
        task_id="say_hello",
        bash_command="echo 'Hello from Airflow 2.7.1 LocalExecutor'",
    )
