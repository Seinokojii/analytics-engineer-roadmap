{{
    config(
        materialized='table',
        tags=['weekly', 'marketing']
    )
}}

-- Тег 'weekly' → запускается раз в неделю
-- Тег 'marketing' → используется маркетинговой командой
SELECT
    {{ date_trunc_safe('week', 'order_date') }}  AS week_start,
    channel,
    {{ revenue_tier('total_amount') }}           AS revenue_tier,
    COUNT(DISTINCT order_id)                     AS order_count,
    SUM(total_amount)                            AS total_revenue,
    {{ safe_divide('SUM(total_amount)',
                   'COUNT(DISTINCT order_id)') }} AS avg_order_value

FROM {{ ref('stg_orders') }}
GROUP BY 1, 2, 3
ORDER BY 1, 2
