{{ config(materialized='table') }}

-- Полная история изменений клиентов (SCD Type 2)
SELECT
    customer_id,
    email,
    plan,
    status,
    dbt_valid_from                          AS valid_from,
    COALESCE(dbt_valid_to,
             '9999-12-31'::TIMESTAMP)       AS valid_to,
    CASE WHEN dbt_valid_to IS NULL
         THEN TRUE ELSE FALSE END           AS is_current,
    DATEDIFF('day',
             dbt_valid_from,
             COALESCE(dbt_valid_to,
                      CURRENT_TIMESTAMP))   AS days_in_state

FROM {{ ref('snap_customers') }}
ORDER BY customer_id, valid_from
