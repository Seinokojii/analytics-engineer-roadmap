-- models/staging/stg_gh_events.sql
-- Day 81-85: normalizatsiya Airbyte raw -> tipizirovannye kolonki
-- [[Airbyte]] [[dbt]] [[Dagster]]
--
-- Snowflake variant togo zhe izvlecheniya:
--   _airbyte_data:event_id::VARCHAR AS event_id

{{
    config(materialized='view', tags=['production_pipeline', 'staging'])
}}

WITH raw AS (
    SELECT
        json_extract_string(_airbyte_data, '$.event_id')        AS event_id,
        json_extract_string(_airbyte_data, '$.event_type')      AS event_type,
        json_extract_string(_airbyte_data, '$.actor')           AS actor_login,
        json_extract_string(_airbyte_data, '$.repo')            AS repo_name,
        CAST(json_extract_string(_airbyte_data, '$.created_at')
             AS TIMESTAMP)                                      AS created_at,
        CAST(json_extract_string(_airbyte_data, '$.payload_size')
             AS INTEGER)                                        AS payload_size,
        _airbyte_partition_date                                 AS event_date,
        _airbyte_extracted_at                                   AS airbyte_extracted_at
    FROM {{ source('gh_raw', 'airbyte_raw_gh_events') }}
    WHERE _airbyte_data IS NOT NULL
)

SELECT
    event_id,
    event_type,
    LOWER(actor_login) AS actor_login,
    repo_name,
    created_at,
    payload_size,
    event_date,
    airbyte_extracted_at
FROM raw
WHERE event_id IS NOT NULL
  AND payload_size > 0
-- Airbyte mozhet dostavit odnu stroku dvazhdy: beryom samuyu svezhuyu
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY event_id ORDER BY airbyte_extracted_at DESC
) = 1
