-- dbt-core 1.12.3, синтаксис time spine по документации dbt Semantic Layer, прогнано на стенде 2026-08-26
-- Календарная таблица с шагом в день. MetricFlow требует такую модель в проекте,
-- чтобы уметь агрегировать метрики по времени независимо от того, есть ли заказы
-- на каждую дату.
{{ config(materialized='table') }}

select generate_series(
    cast('2025-01-01' as date),
    cast('2026-12-31' as date),
    interval '1 day'
)::date as date_day
