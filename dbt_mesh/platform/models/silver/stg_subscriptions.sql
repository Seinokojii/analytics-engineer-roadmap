SELECT
    subscription_id,
    user_id,
    plan,
    mrr::FLOAT       AS mrr,
    start_date::DATE AS start_date,
    end_date::DATE   AS end_date,
    status
FROM {{ ref('raw_subscriptions') }}
WHERE subscription_id IS NOT NULL
