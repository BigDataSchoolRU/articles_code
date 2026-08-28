-- dbt-core 1.12.3, синтаксис Jinja по документации dbt Core, прогнано на стенде 2026-08-28
-- Слой mart: агрегирует staging-модель до дневных показателей по региону.
-- ref() строит зависимость stg_orders -> fct_daily_orders в DAG dbt, а не текстом
-- имени таблицы — dbt сам определяет порядок построения моделей по графу ref().
-- Материализация table (см. dbt_project.yml): агрегат физически пересчитывается
-- и сохраняется, а не оборачивается в view поверх staging при каждом обращении.
select
    order_date,
    region,
    count(*) as orders_count,
    sum(amount) filter (where status = 'completed') as completed_amount,
    sum(amount) as total_amount
from {{ ref('stg_orders') }}
group by order_date, region
