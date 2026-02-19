-- Использование макроса safe_divide
SELECT 
    user_id,
    total_orders,
    total_spent,
    {{ safe_divide('total_spent', 'total_orders') }} AS avg_order_value
FROM {{ ref('dim_customers') }}