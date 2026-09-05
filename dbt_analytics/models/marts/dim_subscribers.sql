{{ config(materialized='table', tags=['saas']) }}
SELECT
    u.user_id,
    u.email,
    u.channel,
    u.country,
    u.signup_date,
    s.plan,
    s.mrr,
    s.start_date AS sub_start_date,
    s.end_date   AS sub_end_date,
    s.status     AS sub_status,
    CASE
        WHEN s.end_date IS NOT NULL
            THEN DATEDIFF('month', s.start_date, s.end_date) * s.mrr
        ELSE DATEDIFF('month', s.start_date, DATE '2025-01-01') * s.mrr
    END AS historical_ltv
FROM {{ ref('stg_saas_users') }} u
LEFT JOIN {{ ref('stg_subscriptions') }} s ON u.user_id = s.user_id
