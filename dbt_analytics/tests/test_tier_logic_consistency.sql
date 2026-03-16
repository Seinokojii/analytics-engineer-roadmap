SELECT *
FROM {{ ref('fct_orders_enriched') }}
WHERE (revenue_tier = 'vip' AND total_amount < 20000)
   OR (revenue_tier = 'high' AND total_amount < 5000)