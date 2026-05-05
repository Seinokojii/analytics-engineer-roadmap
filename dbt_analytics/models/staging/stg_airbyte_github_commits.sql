-- models/staging/stg_airbyte_github_commits.sql
-- Day 80: GitHub commits cherez Airbyte

{{
    config(materialized='view', tags=['airbyte', 'github'])
}}

SELECT
    sha                           AS commit_sha,
    commit:author:name::VARCHAR   AS author_name,
    commit:author:email::VARCHAR  AS author_email,
    commit:author:date::TIMESTAMP AS committed_at,
    commit:message::VARCHAR       AS commit_message,
    _airbyte_extracted_at         AS extracted_at
FROM {{ source('airbyte_raw', '_airbyte_raw_commits') }}
WHERE sha IS NOT NULL
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY sha ORDER BY _airbyte_extracted_at DESC
) = 1
