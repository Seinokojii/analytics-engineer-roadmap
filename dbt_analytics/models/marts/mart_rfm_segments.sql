{{ config(materialized='table') }}
WITH metrics AS (
    SELECT user_id,
           COUNT(DISTINCT subscription_id)                     AS frequency,
           SUM(realized_ltv)                                   AS monetary,
           DATEDIFF('day', MAX(start_date), DATE '2025-01-01') AS recency_days
    FROM {{ ref('fct_subscriptions') }} GROUP BY user_id
),
scored AS (
    SELECT *,
        NTILE(4) OVER (ORDER BY recency_days ASC)  AS r,
        NTILE(4) OVER (ORDER BY frequency DESC)    AS f,
        NTILE(4) OVER (ORDER BY monetary DESC)     AS m
    FROM metrics
)
SELECT *, r+f+m AS rfm_score,
    CASE
        WHEN r+f+m >= 10 THEN 'Champions'
        WHEN r+f+m >= 7  THEN 'Loyal'
        WHEN r >= 3 AND m <= 2 THEN 'New Customers'
        WHEN r <= 2 AND m >= 3 THEN 'At Risk'
        ELSE 'Others'
    END AS segment
FROM scored
