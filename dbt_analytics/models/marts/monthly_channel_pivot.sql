{{ config(materialized='table') }}
SELECT
    DATE_TRUNC('month', created_at) AS order_month,
    {{ pivot_sum(
        values=['completed', 'pending', 'cancelled', 'refunded'],
        column='status',
        agg_column='amount',
        prefix='revenue_'
    ) }},
    {{ count_by_value(
        values=['completed', 'pending', 'cancelled', 'refunded'],
        filter_column='status',
        count_column='order_id',
        prefix='orders_'
    ) }}
FROM {{ ref('stg_orders') }}
GROUP BY 1
ORDER BY 1
