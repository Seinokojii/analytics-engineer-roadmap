{{ config(materialized='table') }}

-- Используем pivot macro — генерирует 3 колонки автоматически
SELECT
    DATE_TRUNC('month', order_date) AS order_month,

    {{ pivot_sum(
        values=['web', 'mobile', 'email'],
        column='channel',
        agg_column='total_amount',
        prefix='revenue_'
    ) }},

    {{ count_by_value(
        values=['web', 'mobile', 'email'],
        filter_column='channel',
        count_column='order_id',
        prefix='orders_'
    ) }}

FROM {{ ref('stg_orders') }}
GROUP BY 1
ORDER BY 1
