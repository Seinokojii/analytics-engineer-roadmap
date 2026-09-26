-- Days 105-107: Dynamic Table - Snowflake sam derzhit vitrinu svezhey
-- v predelakh target_lag. Ni dbt-raspisaniya, ni is_incremental():
-- deklariruesh rezultat i dopustimoe otstavanie, Snowflake reshaet,
-- kogda i kak (incremental ili full) obnovlyat.
-- Vklyuchena tolko na target.type == 'snowflake': na DuckDB takoy
-- materializatsii net, parse upal by na neizvestnom materialized.
-- Ne zapuskalas: Snowflake-akkaunta net.
{{ config(
    enabled=target.type == 'snowflake',
    materialized='dynamic_table',
    target_lag='15 minutes',
    snowflake_warehouse='TRANSFORM_WH',
    refresh_mode='INCREMENTAL'
) }}

SELECT
    DATE_TRUNC('month', start_date) AS month,
    plan,
    COUNT(*)  AS new_subs,
    SUM(mrr)  AS new_mrr
FROM {{ ref('platform', 'fct_subscriptions', v=2) }}
GROUP BY 1, 2
