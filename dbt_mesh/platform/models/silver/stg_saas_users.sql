SELECT
    user_id,
    LOWER(TRIM(email)) AS email,
    channel,
    country,
    signup_date::DATE  AS signup_date
FROM {{ ref('raw_saas_users') }}
WHERE email IS NOT NULL
