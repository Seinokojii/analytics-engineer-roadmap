{{
    config(
        materialized='incremental',
        unique_key='order_id'
    )
}}

SELECT 
    order_id,
    user_id,
    amount,
    created_at
FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
    -- Только новые записи с момента последнего запуска
    WHERE created_at > (SELECT MAX(created_at) FROM {{ this }})
{% endif %}