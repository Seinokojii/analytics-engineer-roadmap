-- Dimension table: Агрегация по клиентам
SELECT 
    u.user_id,
    u.user_name,
    u.email,
    u.city,
    u.created_at AS registration_date,
    COUNT(o.order_id) AS total_orders,
    COALESCE(SUM(o.amount), 0) AS total_spent,
    COALESCE(AVG(o.amount), 0) AS avg_order_value,
    MAX(o.created_at) AS last_order_date
FROM {{ ref('stg_users') }} u
LEFT JOIN {{ ref('stg_orders') }} o ON u.user_id = o.user_id
GROUP BY u.user_id, u.user_name, u.email, u.city, u.created_at