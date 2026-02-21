-- tests/test_tier_logic_consistency.sql
-- Biznes-pravilo: revenue_tier dolzhen sootvetstvovat amount
-- VIP zakazy ne mogut imet amount < 20000

SELECT
    order_id,
    amount,
    revenue_tier
FROM {{ ref('fct_orders_enriched') }}
WHERE (revenue_tier = 'vip' AND amount < 20000)
   OR (revenue_tier = 'low' AND amount >= 5000)