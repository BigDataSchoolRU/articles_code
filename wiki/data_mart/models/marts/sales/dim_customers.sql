-- dbt-core 1.12.6, dbt-duckdb 1.11.1, прогнано на стенде 2026-11-03
-- Измерение «клиент» витрины продаж: одна строка на клиента
select
    customer_id,
    customer_name,
    region,
    segment
from {{ ref('stg_customers') }}
