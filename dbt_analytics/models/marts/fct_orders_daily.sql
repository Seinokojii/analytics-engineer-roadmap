{{ config(materialized='incremental', unique_key='order_id', tags=['daily', 'finance', 'critical']) }}
SELECT
    order_id,
    user_id                        AS customer_id,
    amount                         AS total_amount,
    created_at::DATE               AS order_date,
    status,
    {{ revenue_tier('amount') }}   AS revenue_tier,
    CURRENT_TIMESTAMP              AS loaded_at
FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
WHERE created_at::DATE > (SELECT MAX(order_date) FROM {{ this }})
{% endif %}
