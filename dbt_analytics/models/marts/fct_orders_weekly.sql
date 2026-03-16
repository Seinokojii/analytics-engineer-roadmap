{{ config(materialized='table', tags=['weekly', 'marketing']) }}
SELECT
    DATE_TRUNC('week', created_at)       AS week_start,
    {{ revenue_tier('amount') }}         AS revenue_tier,
    COUNT(DISTINCT order_id)             AS order_count,
    SUM(amount)                          AS total_revenue,
    {{ safe_divide('SUM(amount)', 'COUNT(DISTINCT order_id)') }} AS avg_order_value
FROM {{ ref('stg_orders') }}
GROUP BY 1, 2
ORDER BY 1
