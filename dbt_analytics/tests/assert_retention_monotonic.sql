-- Retention can only fall or stay flat as months pass inside one cohort.
-- Rows returned = violations = test failure.
with r as (
    select cohort_month, month_num, retention_pct,
           lag(retention_pct) over (partition by cohort_month order by month_num) as prev_pct
    from {{ ref('mart_cohort_retention') }}
)
select * from r
where prev_pct is not null and retention_pct > prev_pct
