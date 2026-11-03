-- dbt-core 1.12.6, dbt-duckdb 1.11.1, прогнано на стенде 2026-11-03
-- Staging: типы, имена, фильтр мусора. Бизнес-логики здесь нет.
select
    order_id,
    customer_id,
    cast(order_date as date)          as order_date,
    cast(amount as decimal(12, 2))    as amount,
    status
from {{ source('raw', 'orders') }}
where status = 'paid'   -- отменённые и возвращённые заказы в выручку не идут
