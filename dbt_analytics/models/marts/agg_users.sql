{{
    config(
        materialized='table',
        pre_hook=[
            "CREATE TABLE IF NOT EXISTS audit_log (model_name TEXT, run_at TIMESTAMP)",
            "INSERT INTO audit_log VALUES ('{{ this.name }}', CURRENT_TIMESTAMP)"
        ],
        post_hook=[
            "ANALYZE {{ this }}",
            "CREATE INDEX IF NOT EXISTS idx_{{ this.name }}_user_id ON {{ this }} (user_id)"
        ]
    )
}}

SELECT 
    user_id,
    COUNT(*) AS order_count,
    SUM(amount) AS total_revenue
FROM {{ ref('fct_orders') }}
GROUP BY user_id