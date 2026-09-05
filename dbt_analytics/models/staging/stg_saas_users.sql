{{ config(materialized='view', tags=['saas']) }}
SELECT
    user_id,
    LOWER(TRIM(email)) AS email,
    channel,
    country,
    signup_date::DATE  AS signup_date
FROM {{ source('saas_raw', 'raw_saas_users') }}
WHERE email IS NOT NULL
