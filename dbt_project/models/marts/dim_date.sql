{{ config(materialized='table') }}

-- dbt_utils.date_spine: генерирует таблицу дат без Python
WITH date_spine AS (
    {{ dbt_utils.date_spine(
        datepart='day',
        start_date="cast('2023-01-01' as date)",
        end_date="cast('2025-12-31' as date)"
    ) }}
)

SELECT
    date_day                                        AS date_id,
    date_day,
    EXTRACT(YEAR  FROM date_day)::INT               AS year,
    EXTRACT(MONTH FROM date_day)::INT               AS month,
    EXTRACT(DAY   FROM date_day)::INT               AS day,
    EXTRACT(QUARTER FROM date_day)::INT             AS quarter,
    DAYOFWEEK(date_day)                             AS day_of_week,
    DAYNAME(date_day)                               AS day_name,
    MONTHNAME(date_day)                             AS month_name,
    CASE WHEN DAYOFWEEK(date_day) IN (1, 7)
         THEN TRUE ELSE FALSE END                   AS is_weekend,
    STRFTIME(date_day, '%Y-%m')                     AS year_month,
    STRFTIME(date_day, '%Y') || '-Q' ||
        CAST(EXTRACT(QUARTER FROM date_day) AS VARCHAR) AS year_quarter

FROM date_spine
ORDER BY date_day
