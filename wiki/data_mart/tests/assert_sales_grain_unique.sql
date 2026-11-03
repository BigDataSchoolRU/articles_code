-- dbt-core 1.12.6, прогнано на стенде 2026-11-03
-- Тест зерна витрины: на день × регион × сегмент ровно одна строка. Вернул строки = упал.
select sale_date, region, segment, count(*) as dup
from {{ ref('fct_sales_daily_incr') }}
group by 1, 2, 3
having count(*) > 1
