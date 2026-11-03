-- dbt-core 1.12.6, dbt-duckdb 1.11.1, прогнано на стенде 2026-11-03
-- Витрина продаж, материализация table: каждый запуск пересчитывает всю историю.
-- Зерно: день × регион × сегмент.
select
    o.order_date                    as sale_date,
    c.region,
    c.segment,
    count(*)                        as orders_cnt,
    count(distinct o.customer_id)   as customers_cnt,
    sum(o.amount)                   as revenue
from {{ ref('stg_orders') }} o
join {{ ref('dim_customers') }} c using (customer_id)
group by 1, 2, 3
