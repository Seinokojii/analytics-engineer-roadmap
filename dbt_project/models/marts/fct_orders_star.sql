{{ config(materialized='view') }}

-- dbt_utils.star: SELECT * кроме указанных колонок
-- Удобно когда колонок много и не хочешь перечислять все
SELECT
    {{ dbt_utils.star(from=ref('fct_orders_enriched'),
                      except=['activity_status', 'days_since_order']) }}

FROM {{ ref('fct_orders_enriched') }}
WHERE revenue_tier IN ('high', 'vip')
