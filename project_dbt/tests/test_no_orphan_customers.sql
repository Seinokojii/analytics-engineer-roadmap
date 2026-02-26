SELECT f.order_id, f.customer_id
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ source('ecommerce_dw', 'dim_customers') }} c
    ON f.customer_id = c.customer_id
WHERE c.customer_id IS NULL
