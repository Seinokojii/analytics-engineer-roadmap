{{ config(materialized='table', tags=['saas']) }}
SELECT
    plan,
    COUNT(DISTINCT user_id)          AS subscribers,
    ROUND(AVG(mrr), 2)               AS avg_mrr,
    ROUND(AVG(lifetime_months), 2)   AS avg_lifetime_months,
    ROUND(AVG(realized_ltv), 2)      AS avg_historical_ltv,
    ROUND(AVG(mrr) / CASE plan
        WHEN 'basic'      THEN 0.08
        WHEN 'pro'        THEN 0.05
        WHEN 'enterprise' THEN 0.02
        ELSE 0.05
    END, 2)                          AS predictive_ltv
FROM {{ ref('fct_subscriptions') }}
GROUP BY plan ORDER BY avg_mrr DESC
