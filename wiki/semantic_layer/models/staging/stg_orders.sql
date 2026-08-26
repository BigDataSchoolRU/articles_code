-- dbt-core 1.12.3, синтаксис Jinja по документации dbt Core, прогнано на стенде 2026-08-26
-- Приводит сырую таблицу orders к виду, пригодному для семантической модели:
-- статус приводится к нижнему регистру, добавляется флаг "заказ завершён".
select
    order_id,
    customer_id,
    order_date,
    region,
    lower(status) as status,
    amount,
    (lower(status) = 'completed') as is_completed
from {{ source('raw', 'orders') }}
