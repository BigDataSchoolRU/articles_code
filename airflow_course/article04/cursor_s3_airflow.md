# Проверка файла флага S3 в Airflow
_Exported on 1/31/2026 at 13:28:36 GMT-3 from Cursor (2.4.21)_

---

**User**

"Напиши код для Airflow PythonOperator, который использует S3Hook для проверки: если файл 'flag.txt' существует в бакете, то мы идем дальше, иначе падаем с ошибкой. Используй conn_id='yandex_s3'."

---

**Cursor**


Пишу код с PythonOperator и S3Hook для проверки наличия `flag.txt` в бакете.



Пишу полный пример DAG с PythonOperator:



Удаляю устаревший параметр `provide_context` (в Airflow 2.x контекст передаётся автоматически).



Код лежит в `/home/ubuntu/dags/check_s3_flag_dag.py`. Кратко, что там и как подключать Yandex S3.

**Что делает код**

1. **`check_flag_file`** — вызываемая из PythonOperator функция:
   - создаёт `S3Hook(aws_conn_id="yandex_s3")`;
   - вызывает `hook.check_for_key(key="flag.txt", bucket_name=BUCKET_NAME)`;
   - если ключа нет — выбрасывает `AirflowException` (таск падает);
   - если ключ есть — возвращает строку (таск успешен, можно вешать следующие таски на него).

2. **DAG** — один таск `check_flag_exists`, который вызывает эту функцию. Ниже в DAG можно добавить, например:  
   `check_flag >> next_task`.

**Что нужно сделать тебе**

1. **Задать бакет**  
   Сейчас в коде `BUCKET_NAME = "my-bucket"`. Замени на свой бакет или вынеси в Variable и читай в коде.

2. **Настроить Connection `yandex_s3`**  
   Yandex Object Storage совместим с S3, поэтому используется провайдер Amazon и S3Hook. В Airflow в Connection с id `yandex_s3` укажи:
   - **Connection Type:** `Amazon Web Services` (или оставь как есть, если хук берёт conn_id).
   - **Extra (JSON):**  
     `{"endpoint_url": "https://storage.yandexcloud.net"}`  
   Плюс при необходимости логин/пароль (Access Key ID и Secret Access Key), если провайдер их ожидает в полях connection.

После этого запуск DAG будет проверять наличие `flag.txt` в указанном бакете: есть файл — таск зелёный, нет — таск падает с твоим сообщением в `AirflowException`.

---

**User**

скомбинируй с кодом dag    dags/postgres_to_s3.py    в общий код dags/post_new_s3.py

---

**Cursor**


Ищу файл postgres_to_s3:



Объединяю в один DAG: сначала проверка `flag.txt`, затем выгрузка Postgres → S3.



Создан общий DAG в `dags/post_new_s3.py`. Что в нём сделано:

**Структура DAG**

1. **`check_flag_exists`** — проверка наличия `flag.txt` в бакете через S3Hook (`conn_id='yandex_s3'`). Если файла нет — таск падает с `AirflowException`.
2. **`upload_to_s3`** — выгрузка таблицы `users` из Postgres (conn_id `my_dwh`) в CSV и загрузка в S3.

**Зависимости:** `check_flag >> upload_to_s3` — выгрузка в S3 выполняется только после успешной проверки флага.

**Общие настройки**

- Один `BUCKET_NAME = "airflow-bucket"` и один S3-коннект `yandex_s3` для обоих тасков.
- `KEY_NAME` с шаблоном `{{ ds }}` заменён на формирование ключа внутри функции: `users_export_{ds}.csv` (в callable приходит `ds` из контекста).
- Добавлены `start_date`, `catchup=False`, `schedule=None` и теги.

**Что проверить**

- Connection `yandex_s3` в Airflow (для проверки флага и загрузки).
- Connection `my_dwh` для Postgres.
- Бакет `airflow-bucket` и файл `flag.txt` в нём перед запуском выгрузки.

Если твой `postgres_to_s3.py` лежит в `airflow-course/dags/`, можно скопировать `post_new_s3.py` туда же или добавить эту папку в `dags_folder` в Airflow.

---

**User**

скопировать post_new_s3.py в в airflow-course/dags/

---

**Cursor**


Файл `post_new_s3.py` скопирован в `airflow-course/dags/post_new_s3.py`. DAG будет подхвачен Airflow, если `dags_folder` указывает на `airflow-course/dags/`.

