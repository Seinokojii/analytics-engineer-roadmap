-- models/staging/stg_orders_v2.sql
-- Jinja-���������� ��� ������ ���������

{{ config(materialized='view') }}

{% set completed_status = 'completed' %}
{% set min_amount = 0 %}

SELECT
    order_id,
    user_id,
    amount,
    status,
    created_at::TIMESTAMP AS created_at,

    -- Jinja if/else ����� � SQL
    CASE
        WHEN status = '{{ completed_status }}' THEN true
        ELSE false
    END AS is_completed,

    -- ����� ���������
    '{{ env_var("DBT_ENV", "dev") }}' AS env_label

FROM {{ ref('raw_orders') }}
WHERE amount > {{ min_amount }}
  AND order_id IS NOT NULL