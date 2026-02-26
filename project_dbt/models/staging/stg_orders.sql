{{ config(materialized='view') }}

SELECT
    order_id,
    customer_id,
    product_id,
    date_id         AS order_date,
    quantity,
    unit_price,
    total_amount,
    channel,
    status,
    discount_pct,
    revenue_tier,
    month,
    quarter,
    year,
    payment
FROM {{ source('ecommerce_dw', 'fct_orders') }}
WHERE order_id IS NOT NULL
