{{
    config(
        materialized='incremental',
        unique_key='order_id',
        tags=['daily', 'finance', 'critical']
    )
}}

-- Тег 'daily'  → запускается каждый день
-- Тег 'finance' → входит в финансовые тесты
-- Тег 'critical' → мониторинг в первую очередь
SELECT
    order_id,
    customer_id,
    channel,
    order_date,
    total_amount,
    status,
    {{ revenue_tier('total_amount') }} AS revenue_tier,
    CURRENT_TIMESTAMP                  AS loaded_at

FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
WHERE order_date > (SELECT MAX(order_date) FROM {{ this }})
{% endif %}
