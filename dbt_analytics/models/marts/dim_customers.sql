{{ config(materialized='table') }}

-- Текущее состояние клиентов (только актуальные записи)
SELECT
    customer_id,
    email,
    plan,
    status,
    dbt_valid_from  AS valid_from,
    dbt_updated_at  AS last_updated

FROM {{ ref('snap_customers') }}
WHERE dbt_valid_to IS NULL
