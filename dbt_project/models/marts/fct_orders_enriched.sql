{{ config(materialized='table') }}

-- Используем три macro из разных файлов
SELECT
    order_id,
    customer_id,
    channel,
    order_date,
    total_amount,

    -- macro 1: классификация выручки
    {{ revenue_tier('total_amount') }}              AS revenue_tier,

    -- macro 2: активность (days_since)
    {{ days_since('order_date') }}                  AS days_since_order,
    {{ customer_activity_status(days_since('order_date')) }} AS activity_status,

    -- macro 3: безопасное деление
    {{ safe_divide('total_amount', 'quantity', 0) }} AS unit_price_safe

FROM {{ ref('stg_orders') }}
