-- v2 - breaking change k v1, poetomu otdelnaya versiya, a ne pravka v1:
--   realized_ltv -> ltv_realized  (edinoe imenovanie ltv_* v Gold)
--   is_churned udalen             (vyvoditsya iz status = 'churned')
-- Potrebiteli v1 prodolzhayut rabotat do deprecation_date v1.
SELECT
    subscription_id,
    user_id,
    plan,
    mrr,
    start_date,
    end_date,
    status,
    DATEDIFF('month', start_date,
        COALESCE(end_date, DATE '2025-01-01')) AS lifetime_months,
    mrr * DATEDIFF('month', start_date,
        COALESCE(end_date, DATE '2025-01-01')) AS ltv_realized
FROM {{ ref('stg_subscriptions') }}
