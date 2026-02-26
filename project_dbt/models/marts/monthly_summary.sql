{{ config(materialized='table') }}

SELECT
    month,
    quarter,
    year,
    COUNT(order_id)       AS total_orders,
    SUM(total_amount)     AS gmv,
    ROUND(AVG(total_amount), 0) AS aov,
    COUNT(DISTINCT customer_id) AS active_customers
FROM {{ ref('fct_sales') }}
GROUP BY month, quarter, year
ORDER BY year, month
