-- Staging: Очистка и стандартизация пользователей
SELECT 
    user_id,
    LOWER(TRIM(user_name)) AS user_name,
    LOWER(TRIM(email)) AS email,
    UPPER(city) AS city,
    created_at::TIMESTAMP AS created_at
FROM {{ ref('raw_users') }}
WHERE email IS NOT NULL
  AND email LIKE '%@%'