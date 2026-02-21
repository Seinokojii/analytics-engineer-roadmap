-- tests/test_no_orphan_orders.sql
-- Biznes-pravilo: kazhdyy zakaz dolzhen imet sushchestvuyushchego polzovatelya
-- Orphan = zakaz bez klienta

SELECT
    o.order_id,
    o.user_id
FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id
WHERE u.user_id IS NULL