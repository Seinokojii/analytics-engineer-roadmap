{{ config(materialized='table') }}
SELECT
    {{ dbt_utils.generate_surrogate_key(['order_id', 'user_id']) }} AS order_sk,
    order_id,
    user_id     AS customer_id,
    amount      AS total_amount,
    created_at  AS order_date,
    status
FROM {{ ref('stg_orders') }}
