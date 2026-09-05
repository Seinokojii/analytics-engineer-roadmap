{{ config(materialized='view', tags=['saas']) }}
SELECT
    event_id,
    user_id,
    event_type,
    event_date::DATE AS event_date
FROM {{ source('saas_raw', 'raw_events') }}
