{{ config(materialized='table', tags=['saas']) }}
-- Month-end snapshot: a subscription counts in month m if it started on or
-- before the last day of m and had not ended by then. This is MRR as a
-- balance, not "MRR of subscriptions that started this month".
with months as (
    select unnest(generate_series(date '2023-01-01', date '2024-09-01', interval 1 month))::date as month
),
plans as (
    select distinct plan from {{ ref('fct_subscriptions') }}
),
grid as (
    select m.month, p.plan, last_day(m.month) as month_end
    from months m cross join plans p
)
select g.month, g.plan,
       count(s.subscription_id) filter (where s.start_date <= g.month_end
             and (s.end_date is null or s.end_date > g.month_end))            as active_subs,
       coalesce(sum(s.mrr) filter (where s.start_date <= g.month_end
             and (s.end_date is null or s.end_date > g.month_end)), 0)        as mrr,
       count(s.subscription_id) filter (where date_trunc('month', s.start_date) = g.month) as new_subs,
       count(s.subscription_id) filter (where date_trunc('month', s.end_date) = g.month)   as churned_subs
from grid g
left join {{ ref('fct_subscriptions') }} s on s.plan = g.plan
group by 1, 2
order by 1, 2
