-- tests/test_revenue_consistency.sql
-- Biznes-pravilo: vse zakazy imeyut polozhitelnyy amount
SELECT
    order_id,
    amount
FROM {{ ref('fct_orders') }}
WHERE amount < 0
