-- dbt-core 1.12.6, dbt-duckdb 1.11.1, прогнано на стенде 2026-11-03
select
    customer_id,
    customer_name,
    region,
    segment
from {{ source('raw', 'customers') }}
