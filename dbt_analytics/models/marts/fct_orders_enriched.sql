-- models/marts/fct_orders_enriched.sql
-- ���������� ��� macros � ������, ���������������� ���

{{ config(materialized='table') }}

SELECT
    o.order_id,
    o.user_id,
    u.user_name,
    u.city,
    o.amount,
    o.created_at AS order_date,

    -- ����� macro ������ ����������� CASE WHEN
    {{ classify_revenue_tier('o.amount') }}    AS revenue_tier,
    {{ normalize_status('o.status') }}         AS normalized_status,
    {{ safe_divide('o.amount', '100') }}       AS amount_hundreds,

    EXTRACT(MONTH   FROM o.created_at)         AS order_month,
    EXTRACT(QUARTER FROM o.created_at)         AS order_quarter,
    EXTRACT(YEAR    FROM o.created_at)         AS order_year

FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id