-- Fact table: Заказы с информацией о пользователях
SELECT 
    o.order_id,
    o.user_id,
    u.user_name,
    u.city,
    o.amount,
    o.created_at AS order_date
FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id