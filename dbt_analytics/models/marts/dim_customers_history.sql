{{ config(materialized='table') }}

-- Полная история изменений клиентов (SCD Type 2)
-- Days 101-104: читает Silver (stg_snap_customers), а не snapshot напрямую
SELECT
    customer_id,
    email,
    plan,
    status,
    valid_from,
    COALESCE(valid_to,
             '9999-12-31'::TIMESTAMP)       AS valid_to,
    is_current,
    DATEDIFF('day',
             valid_from,
             COALESCE(valid_to,
                      CURRENT_TIMESTAMP))   AS days_in_state

FROM {{ ref('stg_snap_customers') }}
ORDER BY customer_id, valid_from
