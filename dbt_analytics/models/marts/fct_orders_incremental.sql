-- models/marts/fct_orders_incremental.sql
-- Day 76: Incremental model na Snowflake, strategy: merge

{{
    config(
        materialized         = 'incremental',
        unique_key           = 'order_id',
        incremental_strategy = 'merge',
        cluster_by           = ['order_date'],
        on_schema_change     = 'sync_all_columns',
    )
}}

SELECT
    o.order_id,
    o.user_id,
    o.city,
    o.amount,
    o.order_date
FROM {{ ref('stg_orders') }} o

{% if is_incremental() %}
    WHERE o.order_date >= (
        SELECT DATEADD('day', -3, MAX(order_date)) FROM {{ this }}
    )
{% endif %}
