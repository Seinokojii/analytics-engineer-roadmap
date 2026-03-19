{% snapshot snap_orders_status %}

{{
    config(
        target_schema='snapshots',
        unique_key='order_id',
        strategy='check',
        check_cols=['status'],
    )
}}

-- Snapshot статусов заказов: отслеживаем переходы completed/cancelled
SELECT
    order_id,
    user_id,
    amount,
    status,
    created_at
FROM {{ source('raw', 'raw_orders') }}

{% endsnapshot %}
