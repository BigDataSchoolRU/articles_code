-- dbt-core 1.12.6, dbt-duckdb 1.11.1, прогнано на стенде 2026-11-03
-- Та же витрина продаж, материализация incremental: пересчитываются только свежие дни.
-- delete+insert по ключу зерна: строки с ключами из новой выборки удаляются и вставляются заново.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key=['sale_date', 'region', 'segment']
) }}

select
    o.order_date                    as sale_date,
    c.region,
    c.segment,
    count(*)                        as orders_cnt,
    count(distinct o.customer_id)   as customers_cnt,
    sum(o.amount)                   as revenue
from {{ ref('stg_orders') }} o
join {{ ref('dim_customers') }} c using (customer_id)
{% if is_incremental() %}
-- Берём дни начиная с последнего загруженного минус окно lookback_days.
-- Заказ, опоздавший дальше этого окна, в витрину не попадёт до full-refresh.
where o.order_date >= (
    select max(sale_date) - {{ var('lookback_days') }} from {{ this }}
)
{% endif %}
group by 1, 2, 3
