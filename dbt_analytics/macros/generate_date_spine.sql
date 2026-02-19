{% macro generate_date_spine(start_date, end_date) %}
WITH RECURSIVE date_spine AS (
    SELECT '{{ start_date }}'::DATE AS date
    UNION ALL
    SELECT date + INTERVAL '1 day'
    FROM date_spine
    WHERE date < '{{ end_date }}'::DATE
)
SELECT date FROM date_spine
{% endmacro %}