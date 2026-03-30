-- Churn rate po planu ne mozhet prevyshat 100%
SELECT plan,
    churned * 1.0 / NULLIF(total, 0) AS churn_rate
FROM (
    SELECT plan,
        SUM(CASE WHEN is_churned THEN 1 ELSE 0 END) AS churned,
        COUNT(*) AS total
    FROM {{ ref('fct_subscriptions') }}
    GROUP BY plan
) t
WHERE churned * 1.0 / NULLIF(total, 0) > 1.0
