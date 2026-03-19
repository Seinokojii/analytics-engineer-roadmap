{% snapshot snap_customers %}

{{
    config(
        target_schema='snapshots',
        unique_key='customer_id',
        strategy='timestamp',
        updated_at='updated_at',
    )
}}

-- Snapshot клиентов: отслеживаем изменения plan и status
SELECT
    customer_id,
    email,
    plan,
    status,
    updated_at
FROM {{ source('raw', 'raw_customers') }}

{% endsnapshot %}
