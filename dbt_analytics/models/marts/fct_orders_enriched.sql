{{ config(materialized='table') }}
SELECT
    order_id,
    user_id                                             AS customer_id,
    amount                                              AS total_amount,
    created_at::DATE                                    AS order_date,
    {{ revenue_tier('amount') }}                        AS revenue_tier,
    {{ days_since('created_at') }}                      AS days_since_order,
    {{ customer_activity_status(days_since('created_at')) }} AS activity_status,
    {{ safe_divide('amount', '1', 0) }}                 AS unit_price_safe
FROM {{ ref('stg_orders') }}
