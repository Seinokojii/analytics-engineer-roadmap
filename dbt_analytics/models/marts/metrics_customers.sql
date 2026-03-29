-- models/marts/metrics_customers.sql
{{ config(materialized="table") }}

SELECT
    customer_id,
    email,
    last_updated,
    status
FROM {{ ref('dim_customers') }}
