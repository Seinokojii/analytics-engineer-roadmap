{% snapshot snap_subscribers %}
{{
    config(
        target_schema = 'snapshots',
        unique_key    = 'user_id',
        strategy      = 'check',
        check_cols    = ['plan', 'mrr', 'sub_status'],
    )
}}
SELECT
    user_id, email, plan, mrr,
    sub_start_date, sub_end_date, sub_status
FROM {{ ref('dim_subscribers') }}
{% endsnapshot %}
