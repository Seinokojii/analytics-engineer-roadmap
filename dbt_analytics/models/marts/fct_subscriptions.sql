{{ config(materialized='table', tags=['saas']) }}
SELECT
    subscription_id,
    user_id,
    plan,
    mrr,
    start_date,
    end_date,
    status,
    (status = 'churned') AS is_churned,
    DATEDIFF('month', start_date,
        COALESCE(end_date, DATE '2025-01-01')) AS lifetime_months,
    mrr * DATEDIFF('month', start_date,
        COALESCE(end_date, DATE '2025-01-01')) AS realized_ltv
FROM {{ ref('stg_subscriptions') }}
