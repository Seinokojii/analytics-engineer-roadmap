{{ config(materialized='table') }}

-- Текущее состояние клиентов (только актуальные записи)
-- Days 101-104: читает Silver (stg_snap_customers), а не snapshot напрямую
SELECT
    customer_id,
    email,
    plan,
    status,
    valid_from,
    last_updated

FROM {{ ref('stg_snap_customers') }}
WHERE is_current
