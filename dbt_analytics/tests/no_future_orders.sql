-- tests/no_future_orders.sql
-- Проверка: НЕТ заказов в будущем

SELECT *
FROM {{ ref('fct_orders') }}
WHERE order_date > CURRENT_DATE