-- tests/test_revenue_consistency.sql
-- Biznes-pravilo: dim_customers.total_spent >= 0 vsegda
-- Otritsatelnyy LTV - priznak oshibki v dannykh

SELECT
    user_id,
    total_spent
FROM {{ ref('dim_customers') }}
WHERE total_spent < 0