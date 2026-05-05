-- models/marts/fct_orders_append.sql
-- Day 76: Incremental append — tolko INSERT

{{
    config(
        materialized         = 'incremental',
        unique_key           = 'order_id',
        incremental_strategy = 'append',
    )
}}

SELECT order_id, user_id, amount, city, order_date
FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
    WHERE order_date > (SELECT MAX(order_date) FROM {{ this }})
{% endif %}
