{{ config(materialized='table', tags=['saas']) }}
-- Cohort = month the subscription started. A subscription is "alive" at
-- month k if it had not ended before cohort_month + k months.
-- One subscription per user in this dataset, so this is a survival curve.
--
-- Previous version measured month_num from the subscription's own
-- start_date, so every cohort produced exactly one row (month 0, 100 %).
with subs as (
    select date_trunc('month', start_date)::date as cohort_month,
           start_date, end_date
    from {{ ref('fct_subscriptions') }}
),
k as (
    select unnest(range(0, 13)) as month_num
),
grid as (
    select s.cohort_month, k.month_num,
           s.cohort_month + (k.month_num * interval 1 month) as at_month,
           s.end_date
    from subs s cross join k
),
agg as (
    select cohort_month, month_num,
           count(*) as cohort_size,
           count(*) filter (where end_date is null or end_date >= at_month) as active_subs
    from grid
    group by 1, 2
)
select cohort_month, month_num, cohort_size, active_subs,
       round(active_subs * 100.0 / cohort_size, 2) as retention_pct
from agg
order by cohort_month, month_num
