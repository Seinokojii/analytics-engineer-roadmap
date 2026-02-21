-- tests/test_no_future_orders.sql
-- Biznes-pravilo: zakazy ne mogut byt v budushchem
-- Yesli yest - oshibka v ETL ili testovyye dannyye popali v prod

SELECT
    order_id,
    created_at
FROM {{ ref('stg_orders') }}
WHERE created_at::DATE > CURRENT_DATE