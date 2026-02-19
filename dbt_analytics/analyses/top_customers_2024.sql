-- analyses/top_customers_2024.sql
-- Топ-10 клиентов за 2024 год

WITH orders_2024 AS (
    SELECT 
        user_id,
        SUM(amount) AS revenue_2024
    FROM {{ ref('fct_orders') }}
    WHERE EXTRACT(YEAR FROM order_date) = 2024
    GROUP BY user_id
)
SELECT 
    c.user_name,
    c.city,
    o.revenue_2024,
    c.total_orders
FROM orders_2024 o
JOIN {{ ref('dim_customers') }} c ON o.user_id = c.user_id
ORDER BY o.revenue_2024 DESC
LIMIT 10