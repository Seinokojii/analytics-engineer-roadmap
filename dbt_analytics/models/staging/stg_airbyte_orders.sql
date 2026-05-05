-- models/staging/stg_airbyte_orders.sql
-- Day 80: Normalizatsiya Airbyte dannykh cherez dbt
-- [[Airbyte]] [[Snowflake]]

{{
    config(materialized='view', tags=['airbyte', 'staging'])
}}

WITH raw AS (
    SELECT
        _airbyte_data:id::INTEGER      AS order_id,
        _airbyte_data:user_id::INTEGER AS user_id,
        _airbyte_data:amount::FLOAT    AS amount,
        _airbyte_data:status::VARCHAR  AS status,
        _airbyte_data:city::VARCHAR    AS city,
        _airbyte_data:order_date::DATE AS order_date,
        _airbyte_extracted_at          AS airbyte_extracted_at
    FROM {{ source('airbyte_raw', '_airbyte_raw_orders') }}
    WHERE _airbyte_data IS NOT NULL
)
SELECT
    order_id, user_id,
    ROUND(amount, 2) AS amount,
    LOWER(status)    AS status,
    UPPER(city)      AS city,
    order_date, airbyte_extracted_at
FROM raw
WHERE order_id IS NOT NULL AND amount > 0
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY order_id ORDER BY airbyte_extracted_at DESC
) = 1
