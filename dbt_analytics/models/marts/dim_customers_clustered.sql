-- models/marts/dim_customers_clustered.sql
-- Day 77: Clustering Key po city

{{
    config(
        materialized = 'table',
        cluster_by   = ['city'],
    )
}}

SELECT
    u.user_id, u.email, u.city, u.channel,
    COUNT(o.order_id)       AS total_orders,
    ROUND(SUM(o.amount), 2) AS total_spent,
    ROUND(AVG(o.amount), 2) AS avg_order_value,
    MAX(o.order_date)       AS last_order_date
FROM {{ ref('stg_users') }} u
LEFT JOIN {{ ref('stg_orders') }} o ON u.user_id = o.user_id
GROUP BY u.user_id, u.email, u.city, u.channel
