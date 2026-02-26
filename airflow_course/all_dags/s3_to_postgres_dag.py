"""
DAG для загрузки данных из S3 в Postgres.

Использует TaskFlow API (@task), S3Hook и PostgresHook.
Перед запуском: установи провайдеры (если их нет в образе):
  apache-airflow-providers-amazon, apache-airflow-providers-postgres
И настрой Connection в Airflow: aws_default (или s3_default), postgres_default.
"""

from datetime import datetime

from airflow.decorators import dag, task
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from airflow.providers.postgres.hooks.postgres import PostgresHook


@dag(
    dag_id="02.s3_to_postgres",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["s3", "postgres", "etl", "taskflow"],
)
def s3_to_postgres():
    """
    DAG для загрузки данных из S3 в Postgres (TaskFlow API).

    Параметры @dag:
    ---------------
    dag_id : str
        Уникальный ID DAG. Используется в UI, API, логах.
        Префикс '02.' — для сортировки в списке DAG'ов.

    start_date : datetime
        Дата, с которой Airflow начинает планировать запуски.
        Важно: для срабатывания по расписанию start_date должен быть в прошлом.
        Используем фиксированную дату, а не days_ago(), чтобы DAG был детерминированным.

    schedule : str | None
        Расписание (cron, @daily, timedelta) или None.
        None = только ручной запуск. Поставь, например, '@daily' для ежедневного запуска.

    catchup : bool
        False — не создавать «догоняющие» запуски за прошлые периоды.
        True — выполнить все пропущенные интервалы с start_date (часто нежелательно).

    tags : list[str]
        Метки для фильтрации и поиска DAG'ов в UI.
    """

    @task
    def fetch_from_s3(
        bucket: str,
        key: str,
        aws_conn_id: str = "aws_default",
    ) -> dict:
        """
        Читает объект из S3 с помощью S3Hook.

        Parameters
        ----------
        bucket : str
            Имя S3-бакета, откуда читаем файл.

        key : str
            Ключ объекта в бакете (путь к файлу), например 'data/raw/2025-01-25.csv'.

        aws_conn_id : str, default 'aws_default'
            ID Airflow Connection с кредами AWS (Access Key, Secret Key, регион).
            S3Hook возьмёт их из Connection — не нужно хардкодить в коде.

        Returns
        -------
        dict
            Метаданные для следующей задачи: bucket, key.
            В реальном ETL тут мог бы быть путь к скачанному файлу (в volume).
        """
        hook = S3Hook(aws_conn_id=aws_conn_id)
        # Проверяем наличие объекта; в полноценном ETL — читаем содержимое
        # или сохраняем в /tmp / volume и возвращаем путь.
        obj = hook.get_key(key=key, bucket_name=bucket)
        if obj is None:
            raise ValueError(f"Объект s3://{bucket}/{key} не найден.")
        return {"bucket": bucket, "key": key}

    @task
    def load_to_postgres(
        s3_meta: dict,
        table: str,
        postgres_conn_id: str = "postgres_default",
    ) -> None:
        """
        Загружает данные в Postgres (скелет: здесь только структура).

        Parameters
        ----------
        s3_meta : dict
            Результат из fetch_from_s3 (XCom): bucket, key.
            В реальном пайплайне по ключу можно снова прочитать файл из S3
            или использовать общий volume между тасками.

        table : str
            Имя целевой таблицы в Postgres, например 'staging.s3_landing'.

        postgres_conn_id : str, default 'postgres_default'
            ID Airflow Connection к Postgres (host, port, user, password, dbname).
            PostgresHook использует его для подключения — без секретов в коде.
        """
        pg = PostgresHook(postgres_conn_id=postgres_conn_id)
        # Скелет: в проде здесь был бы COPY / INSERT из файла.
        # Таблица должна существовать, например:
        #   CREATE TABLE staging.s3_landing (
        #     source_bucket TEXT, source_key TEXT, loaded_at TIMESTAMPTZ
        #   );
        sql = f"""
            INSERT INTO {table} (source_bucket, source_key, loaded_at)
            VALUES (%(bucket)s, %(key)s, NOW());
        """
        pg.run(
            sql,
            parameters={
                "bucket": s3_meta["bucket"],
                "key": s3_meta["key"],
            },
        )

    meta = fetch_from_s3(bucket="my-bucket", key="data/raw/sample.csv")
    load_to_postgres(s3_meta=meta, table="staging.s3_landing")


# Инстанцируем DAG
s3_to_postgres()


# --- Почему S3Hook, а не boto3 напрямую? ---
#
# 1. Connection-based доступ.
#    Креды хранятся в Airflow Connections (Admin → Connections), а не в коде.
#    Меняешь окружение (dev/prod) — меняешь только Connection, DAG тот же.
#
# 2. Единообразие и тестирование.
#    S3Hook — обёртка над boto3 с фиксированным API. Легко мокать в тестах
#    и использовать те же вызовы в разных DAG'ах.
#
# 3. Интеграция с Airflow.
#    Логи, retry, метрики — всё через Hook. При падении таски видно именно
#    «таск с S3», а не «где-то упал boto3».
#
# 4. Меньше бойлерплейта.
#    Не нужно самому создавать client, обрабатывать creds, регионы.
#    Hook уже умеет get_key, read_key, load_file и т.д.
#
# 5. Безопасность.
#    Секреты не попадают в репозиторий и не дублируются в default_args.
#
# boto3 напрямую имеет смысл, когда нужна очень специфичная логика
# (например, сложная работа с Glacier, TransferConfig и т.п.),
# которую Hook не покрывает. Для типичной загрузки из S3 S3Hook — предпочтительный вариант.
