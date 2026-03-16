{{ config(materialized='table') }}

-- dbt_utils.surrogate_key создаёт MD5-хэш из нескольких колонок
-- Используется когда нет натурального первичного ключа
SELECT
    {{ dbt_utils.surrogate_key(['order_id', 'customer_id']) }} AS order_sk,
    order_id,
    customer_id,
    channel,
    order_date,
    total_amount,
    status

FROM {{ ref('stg_orders') }}
