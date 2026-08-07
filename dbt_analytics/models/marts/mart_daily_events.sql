-- models/marts/mart_daily_events.sql
-- Day 81-85: inkrementalnyy mart po dnyam
-- DuckDB ne umeet MERGE bez PK -> strategiya delete+insert

{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='event_date',
        tags=['production_pipeline', 'marts']
    )
}}

SELECT
    event_date,
    COUNT(*)                                                   AS events,
    COUNT(DISTINCT actor_login)                                AS active_actors,
    COUNT(DISTINCT repo_name)                                  AS active_repos,
    SUM(CASE WHEN event_type = 'PushEvent' THEN 1 ELSE 0 END)  AS pushes,
    SUM(CASE WHEN event_type = 'PullRequestEvent'
             THEN 1 ELSE 0 END)                                AS pull_requests,
    SUM(CASE WHEN event_type = 'WatchEvent' THEN 1 ELSE 0 END) AS stars,
    ROUND(AVG(payload_size), 1)                                AS avg_payload_size
FROM {{ ref('stg_gh_events') }}

{% if is_incremental() %}
-- Perechityvaem tolko svezhie partitsii, a ne vsyu istoriyu
WHERE event_date >= (SELECT COALESCE(MAX(event_date), '1970-01-01') FROM {{ this }})
{% endif %}

GROUP BY event_date
