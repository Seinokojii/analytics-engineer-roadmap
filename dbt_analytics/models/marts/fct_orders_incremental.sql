-- models/marts/fct_orders_incremental.sql
-- Incremental: ��� ��������� �������� ��������� ������ ����� ������

{{
    config(
        materialized    = 'incremental',
        unique_key      = 'order_id',
        on_schema_change = 'sync_all_columns'
    )
}}

SELECT
    order_id,
    user_id,
    amount,
    status,
    {{ classify_revenue_tier('amount') }} AS revenue_tier,
    created_at,
    CURRENT_TIMESTAMP                     AS loaded_at

FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
    -- ���� ���� ����������� ������ ��� incremental-������� (�� ��� ������)
    -- {{ this }} = ������� ������� � ��
    WHERE created_at > (
        SELECT MAX(created_at)
        FROM {{ this }}
    )
{% endif %}