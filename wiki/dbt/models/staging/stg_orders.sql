-- dbt-core 1.12.3, синтаксис Jinja по документации dbt Core, прогнано на стенде 2026-08-28
-- Слой staging: приводит сырую таблицу orders к чистому виду один в один по строкам,
-- без агрегации. Материализация view (см. dbt_project.yml) — слой staging не хранит
-- собственных данных, только переиспользуемый SQL поверх источника.
select
    order_id,
    customer_id,
    order_date,
    region,
    lower(status) as status,
    amount
from {{ source('raw', 'orders') }}
