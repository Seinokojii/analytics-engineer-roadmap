-- models/marts/monthly_revenue_pivot.sql
-- Jinja for-loop: ���������� 12 ������� �������������
-- ������ ������� ��������� 12 ���������� CASE WHEN

{{ config(materialized='table') }}

{% set months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] %}

SELECT
    user_id,

    {% for month in months %}
    SUM(CASE
        WHEN EXTRACT(MONTH FROM created_at) = {{ month }}
        THEN amount
        ELSE 0
    END) AS revenue_month_{{ month }}
    {% if not loop.last %},{% endif %}
    {% endfor %}

FROM {{ ref('stg_orders') }}
WHERE status = 'completed'
GROUP BY user_id
ORDER BY user_id