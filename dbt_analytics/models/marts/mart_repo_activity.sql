-- models/marts/mart_repo_activity.sql
-- Day 81-85: aktivnost po repozitoriyam za vsyu istoriyu

{{
    config(materialized='table', tags=['production_pipeline', 'marts'])
}}

WITH events AS (
    SELECT * FROM {{ ref('stg_gh_events') }}
)

SELECT
    repo_name,
    COUNT(*)                                                   AS events,
    COUNT(DISTINCT actor_login)                                AS contributors,
    COUNT(DISTINCT event_date)                                 AS active_days,
    SUM(CASE WHEN event_type = 'PushEvent' THEN 1 ELSE 0 END)  AS pushes,
    SUM(CASE WHEN event_type = 'PullRequestEvent'
             THEN 1 ELSE 0 END)                                AS pull_requests,
    MIN(event_date)                                            AS first_event_date,
    MAX(event_date)                                            AS last_event_date,
    ROUND(
        COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT event_date), 0), 2
    )                                                          AS events_per_day
FROM events
GROUP BY repo_name
