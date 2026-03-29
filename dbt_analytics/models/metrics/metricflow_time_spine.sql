-- models/metrics/metricflow_time_spine.sql
-- Required by MetricFlow: provides date spine for time dimensions.
-- Pure DuckDB generate_series -- no dbt_utils macro needed.

{{ config(materialized='table') }}

SELECT
    CAST(gs AS DATE) AS date_day
FROM GENERATE_SERIES(
    DATE '2020-01-01',
    DATE '2030-01-01',
    INTERVAL '1 day'
) AS t(gs)
