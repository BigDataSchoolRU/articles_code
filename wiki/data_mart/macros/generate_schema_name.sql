-- dbt-core 1.12.6, прогнано на стенде 2026-11-03
-- Схема модели берётся как есть (staging, marts), без префикса схемы профиля
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
