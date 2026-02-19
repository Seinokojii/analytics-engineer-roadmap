-- Staging: Фильтрация только completed заказов
SELECT 
    order_id,
    user_id,
    amount,
    status,
    created_at::TIMESTAMP AS created_at
FROM {{ ref('raw_orders') }}
WHERE status = 'completed'
  AND amount > 0