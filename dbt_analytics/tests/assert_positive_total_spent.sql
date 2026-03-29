-- tests/assert_positive_total_spent.sql
-- Proverka: amount ne mozhet byt otricatelnym
SELECT *
FROM {{ ref('fct_orders') }}
WHERE amount < 0
