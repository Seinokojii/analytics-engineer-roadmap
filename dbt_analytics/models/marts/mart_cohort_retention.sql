{{ config(materialized='table') }}
WITH first_sub AS (
    SELECT user_id,
           DATE_TRUNC('month', MIN(start_date)) AS cohort_month
    FROM {{ ref('stg_subscriptions') }} GROUP BY user_id
),
activity AS (
    SELECT s.user_id, f.cohort_month,
           DATEDIFF('month', f.cohort_month,
               DATE_TRUNC('month', s.start_date)) AS month_num
    FROM {{ ref('stg_subscriptions') }} s
    JOIN first_sub f ON s.user_id = f.user_id
),
agg AS (
    SELECT cohort_month, month_num,
           COUNT(DISTINCT user_id) AS active_users
    FROM activity GROUP BY cohort_month, month_num
)
SELECT cohort_month, month_num, active_users,
    FIRST_VALUE(active_users) OVER (
        PARTITION BY cohort_month ORDER BY month_num
    ) AS cohort_size,
    ROUND(active_users * 100.0 /
        FIRST_VALUE(active_users) OVER (
            PARTITION BY cohort_month ORDER BY month_num
        ), 2) AS retention_pct
FROM agg WHERE month_num <= 12
ORDER BY cohort_month, month_num
