from airflow import DAG
from airflow.providers.postgres.operators.postgres import PostgresOperator
from datetime import datetime
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook

def check_user_count():
    # Инициализируем хук, используя тот же conn_id
    pg_hook = PostgresHook(postgres_conn_id="my_dwh")

    # Хук дает нам метод get_records для выполнения SQL и получения результата
    records = pg_hook.get_records(sql="SELECT COUNT(*) FROM users;")

    # Результат возвращается как список кортежей: [(3,)]
    count = records[0][0]
    print(f"Всего пользователей в базе: {count}")

    if count > 2:
        print("База успешно наполнена!")
    else:
        raise ValueError("Что-то пошло не так, данных слишком мало!")

# Определяем SQL запросы прямо здесь или выносим в отдельные файлы
create_table_sql = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50),
    signup_date DATE
);
"""

insert_data_sql = """
INSERT INTO users (name, signup_date) VALUES 
('Alice', '2023-01-01'),
('Charlie', '2023-01-03');
"""

with DAG(
    dag_id="03.simple_postgres_etl",
    start_date=datetime(2023, 1, 1),
    schedule=None,
    catchup=False
) as dag:

    # Шаг 1: Создаем структуру
    create_task = PostgresOperator(
        task_id="create_table",
        postgres_conn_id="my_dwh", # Ссылаемся на Connection, который создали в UI
sql=create_table_sql
    )

    # Шаг 2: Чистим старые данные (для идемпотентности)
    clean_task = PostgresOperator(
        task_id="clean_table",
        postgres_conn_id="my_dwh",
        sql="TRUNCATE TABLE users;"
    )

    # Шаг 3: Наливаем данные
    fill_task = PostgresOperator(
        task_id="fill_table",
        postgres_conn_id="my_dwh",
        sql=insert_data_sql
    )

    # Создаем задачу PythonOperator
    check_task = PythonOperator(
        task_id="check_data_quality",
        python_callable=check_user_count
    )

    # Задаем порядок выполнения
    create_task >> clean_task >> fill_task >> check_task
