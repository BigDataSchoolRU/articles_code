"""
DAG для автоматического выполнения Jupyter Notebook отчетов.

Этот DAG использует PapermillOperator для выполнения Jupyter Notebook,
что позволяет автоматизировать создание отчетов с графиками и вычислениями.
"""

# Импорт необходимых модулей Airflow
from airflow import DAG  # Базовый класс для создания DAG (Directed Acyclic Graph)
from airflow.providers.papermill.operators.papermill import PapermillOperator  # Оператор для выполнения Jupyter Notebook
from airflow.utils.dates import days_ago  # Утилита для работы с датами

# Аргументы по умолчанию для всех задач в DAG
# Эти параметры будут применены ко всем задачам, если не указаны явно
default_args = {
    'owner': 'data_engineer',  # Владелец DAG (для отслеживания ответственности)
    'start_date': days_ago(1),  # Дата начала выполнения DAG (1 день назад от текущей даты)
    # start_date определяет, с какой даты Airflow начнет планировать запуски
}

# Создание DAG с использованием контекстного менеджера (with)
# Контекстный менеджер гарантирует правильную инициализацию и регистрацию DAG
with DAG(
    # Уникальный идентификатор DAG (должен быть уникальным в рамках Airflow)
    # Префикс '01.' используется для сортировки DAG в веб-интерфейсе
    dag_id='01.jupyter_automated_report',
    
    # Применение аргументов по умолчанию ко всем задачам
    default_args=default_args,
    
    # Расписание выполнения DAG
    # '@daily' означает запуск один раз в день в полночь (00:00)
    # Другие варианты: '@hourly', '@weekly', '@monthly', cron-выражения ('0 0 * * *')
    schedule_interval='@daily',
    
    # Отключение catchup (догоняющих запусков)
    # Если False: Airflow не будет создавать пропущенные запуски за прошлые периоды
    # Если True: Airflow создаст все пропущенные запуски с момента start_date
    # Рекомендуется False для предотвращения неожиданных массовых запусков
    catchup=False
) as dag:
    # Переменная 'dag' теперь содержит объект DAG, к которому можно добавлять задачи

    # Создание задачи с использованием PapermillOperator
    # PapermillOperator выполняет Jupyter Notebook и сохраняет результат
    run_notebook_task = PapermillOperator(
        # Уникальный идентификатор задачи внутри DAG
        task_id='run_daily_report',
        
        # Путь к исходному шаблону Jupyter Notebook
        # Это файл .ipynb, который будет выполнен
        # Путь указан относительно контейнера Airflow (/opt/airflow/dags/)
        input_nb='/opt/airflow/dags/notebook/report_template.ipynb',
        
        # Путь для сохранения исполненного ноутбука
        # {{ ds }} - это макрос Airflow, который подставит дату выполнения в формате YYYY-MM-DD
        # Например: report_2026-01-25.ipynb
        # Исполненный ноутбук будет содержать:
        #   - Все результаты вычислений
        #   - Сгенерированные графики и визуализации
        #   - Логи выполнения ячеек
        output_nb='/opt/airflow/dags/notebook/report_{{ ds }}.ipynb',
        
        # Параметры для передачи в Jupyter Notebook
        # Эти параметры будут доступны в ноутбуке через переменную 'parameters'
        # В ноутбуке можно использовать: parameters['execution_date'] и parameters['threshold']
        parameters={
            'execution_date': '{{ ds }}',  # Дата выполнения DAG (макрос Airflow)
            'threshold': 250  # Пороговое значение для фильтрации данных
        }
    )
    
    # Примечание: если бы было несколько задач, их можно было бы связать:
    # task1 >> task2  # task2 выполнится после task1
    # task1 >> [task2, task3]  # task2 и task3 выполнятся параллельно после task1


