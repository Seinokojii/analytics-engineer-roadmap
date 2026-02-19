-- tests/assert_positive_total_spent.sql
-- Проверка: total_spent не может быть отрицательным

SELECT *
FROM {{ ref('dim_customers') }}
WHERE total_spent < 0