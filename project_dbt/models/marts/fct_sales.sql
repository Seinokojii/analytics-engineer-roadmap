{{ config(materialized='table') }}

SELECT
    o.order_id,
    o.customer_id,
    o.product_id,
    o.order_date,
    o.quantity,
    o.unit_price,
    o.total_amount,
    o.channel,
    o.status,
    o.discount_pct,
    o.revenue_tier,
    o.month,
    o.quarter,
    o.year,
    CASE
        WHEN o.total_amount >= 20000 THEN 'VIP'
        WHEN o.total_amount >= 5000  THEN 'High'
        WHEN o.total_amount >= 1000  THEN 'Medium'
        ELSE 'Low'
    END AS value_segment
FROM {{ ref('stg_orders') }} o
WHERE o.status = 'completed'
