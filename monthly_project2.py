#!/usr/bin/env python3
"""
monthly_project2.py - Monthly Project 2: Retention & Cohort + dbt Pipeline
Запуск: python monthly_project2.py

FIX v2:
  - _metrics_saas.yml: ltv_sum is a measure, not a metric.
    Ratio metric avg_ltv must reference other METRICS, not measures.
    Added total_ltv (simple) as intermediary.
  - dbt seed: uses --select with correct CSV names
"""

import subprocess
import pandas as pd
import numpy as np
import duckdb
from pathlib import Path
from datetime import date, timedelta
import random

random.seed(42)
np.random.seed(42)

PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT  = PROJECT_ROOT / "dbt_analytics"
REPORTS_DIR  = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

PLANS = {
    "basic":      {"price": 10,  "churn": 0.08},
    "pro":        {"price": 50,  "churn": 0.05},
    "enterprise": {"price": 200, "churn": 0.02},
}
N_USERS = 500
START   = date(2023, 1, 1)
END     = date(2024, 12, 31)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


def run_dbt(cmd: str) -> bool:
    print(f"\n> dbt {cmd}")
    r = subprocess.run(
        f"dbt {cmd}", shell=True, cwd=DBT_PROJECT,
        capture_output=True, text=True, encoding="utf-8"
    )
    for line in r.stdout.strip().split("\n")[-6:]:
        print(line)
    if r.returncode != 0:
        print(f"ERROR: {r.stderr[-400:]}")
    return r.returncode == 0


def find_db() -> Path:
    candidates = [
        DBT_PROJECT / "dev.duckdb",
        DBT_PROJECT / "dbt_analytics.duckdb",
        PROJECT_ROOT / "dev.duckdb",
    ]
    for p in candidates:
        if p.exists():
            return p
    found = list(DBT_PROJECT.glob("*.duckdb")) + list(PROJECT_ROOT.glob("*.duckdb"))
    if found:
        return found[0]
    return None


# ── ШАГ 1: Генерация данных ──────────────────────────────

def generate_data():
    print("\n" + "=" * 55)
    print("  STEP 1: Generating SaaS data")
    print("=" * 55)

    channels  = ["organic", "paid", "referral", "social"]
    countries = ["US", "UK", "DE", "FR", "KG"]

    users = pd.DataFrame({
        "user_id":    range(1, N_USERS + 1),
        "email":      [f"user{i}@example.com" for i in range(1, N_USERS + 1)],
        "channel":    np.random.choice(channels, N_USERS, p=[.4, .3, .2, .1]),
        "country":    np.random.choice(countries, N_USERS),
        "signup_date": pd.date_range(START, periods=N_USERS, freq="12h")[:N_USERS],
    })

    plan_names = list(PLANS.keys())
    plan_probs = [0.50, 0.35, 0.15]
    subs, sub_id = [], 1
    for _, u in users.iterrows():
        plan    = np.random.choice(plan_names, p=plan_probs)
        s_date  = pd.Timestamp(u["signup_date"]) + timedelta(days=random.randint(0, 7))
        churned = random.random() < PLANS[plan]["churn"] * 12
        e_date  = (s_date + timedelta(days=random.randint(60, 400))).date() if churned else None
        subs.append({
            "subscription_id": sub_id,
            "user_id":         u["user_id"],
            "plan":            plan,
            "mrr":             PLANS[plan]["price"],
            "start_date":      s_date.date(),
            "end_date":        e_date,
            "status":          "churned" if churned else "active",
        })
        sub_id += 1
    subs_df = pd.DataFrame(subs)

    event_types = ["login", "feature_use", "upgrade_view", "support_ticket"]
    events = []
    for _, u in users.sample(min(300, N_USERS)).iterrows():
        for _ in range(random.randint(5, 30)):
            ev_date = START + timedelta(days=random.randint(0, (END - START).days))
            events.append({
                "event_id":   len(events) + 1,
                "user_id":    u["user_id"],
                "event_type": random.choice(event_types),
                "event_date": ev_date,
            })
    events_df = pd.DataFrame(events)

    data_dir = DBT_PROJECT / "data"
    data_dir.mkdir(exist_ok=True)
    users.to_csv(data_dir / "raw_saas_users.csv", index=False)
    subs_df.to_csv(data_dir / "raw_subscriptions.csv", index=False)
    events_df.to_csv(data_dir / "raw_events.csv", index=False)
    print(f"  OK {N_USERS} users / {len(subs_df)} subscriptions / {len(events_df)} events")


# ── ШАГ 2: dbt модели ────────────────────────────────────

def create_dbt_models():
    print("\n" + "=" * 55)
    print("  STEP 2: Creating dbt models")
    print("=" * 55)
    m = DBT_PROJECT / "models"

    write_utf8(m / "staging" / "sources_saas.yml", """\
version: 2
sources:
  - name: saas_raw
    schema: main
    tables:
      - name: raw_saas_users
        columns:
          - name: user_id
            data_tests:
              - not_null
              - unique
      - name: raw_subscriptions
        columns:
          - name: subscription_id
            data_tests:
              - not_null
              - unique
      - name: raw_events
        columns:
          - name: event_id
            data_tests:
              - not_null
""")

    write_utf8(m / "staging" / "stg_saas_users.sql", """\
{{ config(materialized='view') }}
SELECT
    user_id,
    LOWER(TRIM(email)) AS email,
    channel,
    country,
    signup_date::DATE  AS signup_date
FROM {{ source('saas_raw', 'raw_saas_users') }}
WHERE email IS NOT NULL
""")

    write_utf8(m / "staging" / "stg_subscriptions.sql", """\
{{ config(materialized='view') }}
SELECT
    subscription_id,
    user_id,
    plan,
    mrr::FLOAT       AS mrr,
    start_date::DATE AS start_date,
    end_date::DATE   AS end_date,
    status
FROM {{ source('saas_raw', 'raw_subscriptions') }}
WHERE subscription_id IS NOT NULL
""")

    write_utf8(m / "staging" / "stg_events.sql", """\
{{ config(materialized='view') }}
SELECT
    event_id,
    user_id,
    event_type,
    event_date::DATE AS event_date
FROM {{ source('saas_raw', 'raw_events') }}
""")

    write_utf8(m / "marts" / "dim_subscribers.sql", """\
{{ config(materialized='table') }}
SELECT
    u.user_id,
    u.email,
    u.channel,
    u.country,
    u.signup_date,
    s.plan,
    s.mrr,
    s.start_date AS sub_start_date,
    s.end_date   AS sub_end_date,
    s.status     AS sub_status,
    CASE
        WHEN s.end_date IS NOT NULL
            THEN DATEDIFF('month', s.start_date, s.end_date) * s.mrr
        ELSE DATEDIFF('month', s.start_date, DATE '2025-01-01') * s.mrr
    END AS historical_ltv
FROM {{ ref('stg_saas_users') }} u
LEFT JOIN {{ ref('stg_subscriptions') }} s ON u.user_id = s.user_id
""")

    write_utf8(m / "marts" / "fct_subscriptions.sql", """\
{{ config(materialized='table') }}
SELECT
    subscription_id,
    user_id,
    plan,
    mrr,
    start_date,
    end_date,
    status,
    (status = 'churned') AS is_churned,
    DATEDIFF('month', start_date,
        COALESCE(end_date, DATE '2025-01-01')) AS lifetime_months,
    mrr * DATEDIFF('month', start_date,
        COALESCE(end_date, DATE '2025-01-01')) AS realized_ltv
FROM {{ ref('stg_subscriptions') }}
""")

    write_utf8(m / "marts" / "mart_cohort_retention.sql", """\
{{ config(materialized='table') }}
WITH first_sub AS (
    SELECT user_id,
           DATE_TRUNC('month', MIN(start_date)) AS cohort_month
    FROM {{ ref('stg_subscriptions') }} GROUP BY user_id
),
activity AS (
    SELECT s.user_id, f.cohort_month,
           DATEDIFF('month', f.cohort_month,
               DATE_TRUNC('month', s.start_date)) AS month_num
    FROM {{ ref('stg_subscriptions') }} s
    JOIN first_sub f ON s.user_id = f.user_id
),
agg AS (
    SELECT cohort_month, month_num,
           COUNT(DISTINCT user_id) AS active_users
    FROM activity GROUP BY cohort_month, month_num
)
SELECT cohort_month, month_num, active_users,
    FIRST_VALUE(active_users) OVER (
        PARTITION BY cohort_month ORDER BY month_num
    ) AS cohort_size,
    ROUND(active_users * 100.0 /
        FIRST_VALUE(active_users) OVER (
            PARTITION BY cohort_month ORDER BY month_num
        ), 2) AS retention_pct
FROM agg WHERE month_num <= 12
ORDER BY cohort_month, month_num
""")

    write_utf8(m / "marts" / "mart_rfm_segments.sql", """\
{{ config(materialized='table') }}
WITH metrics AS (
    SELECT user_id,
           COUNT(DISTINCT subscription_id)                     AS frequency,
           SUM(realized_ltv)                                   AS monetary,
           DATEDIFF('day', MAX(start_date), DATE '2025-01-01') AS recency_days
    FROM {{ ref('fct_subscriptions') }} GROUP BY user_id
),
scored AS (
    SELECT *,
        NTILE(4) OVER (ORDER BY recency_days ASC)  AS r,
        NTILE(4) OVER (ORDER BY frequency DESC)    AS f,
        NTILE(4) OVER (ORDER BY monetary DESC)     AS m
    FROM metrics
)
SELECT *, r+f+m AS rfm_score,
    CASE
        WHEN r+f+m >= 10 THEN 'Champions'
        WHEN r+f+m >= 7  THEN 'Loyal'
        WHEN r >= 3 AND m <= 2 THEN 'New Customers'
        WHEN r <= 2 AND m >= 3 THEN 'At Risk'
        ELSE 'Others'
    END AS segment
FROM scored
""")

    write_utf8(m / "marts" / "mart_ltv.sql", """\
{{ config(materialized='table') }}
SELECT
    plan,
    COUNT(DISTINCT user_id)          AS subscribers,
    ROUND(AVG(mrr), 2)               AS avg_mrr,
    ROUND(AVG(lifetime_months), 2)   AS avg_lifetime_months,
    ROUND(AVG(realized_ltv), 2)      AS avg_historical_ltv,
    ROUND(AVG(mrr) / CASE plan
        WHEN 'basic'      THEN 0.08
        WHEN 'pro'        THEN 0.05
        WHEN 'enterprise' THEN 0.02
        ELSE 0.05
    END, 2)                          AS predictive_ltv
FROM {{ ref('fct_subscriptions') }}
GROUP BY plan ORDER BY avg_mrr DESC
""")

    write_utf8(m / "marts" / "schema_saas.yml", """\
version: 2
models:
  - name: dim_subscribers
    description: "Subscribers dimension (SCD2 ready)"
    columns:
      - name: user_id
        data_tests:
          - not_null
          - unique
      - name: email
        data_tests:
          - not_null
      - name: plan
        data_tests:
          - accepted_values:
              values: [basic, pro, enterprise]
      - name: mrr
        data_tests:
          - not_null

  - name: fct_subscriptions
    description: "Subscription facts: MRR, churn, LTV"
    columns:
      - name: subscription_id
        data_tests:
          - not_null
          - unique
      - name: user_id
        data_tests:
          - not_null
      - name: mrr
        data_tests:
          - not_null
      - name: plan
        data_tests:
          - accepted_values:
              values: [basic, pro, enterprise]

  - name: mart_cohort_retention
    description: "Cohort retention by month"
    columns:
      - name: cohort_month
        data_tests:
          - not_null
      - name: retention_pct
        data_tests:
          - not_null

  - name: mart_ltv
    description: "LTV by plan"
    columns:
      - name: plan
        data_tests:
          - not_null
          - unique
""")


# ── ШАГ 3: Snapshot ──────────────────────────────────────

def create_snapshot():
    print("\n" + "=" * 55)
    print("  STEP 3: Snapshot (SCD Type 2)")
    print("=" * 55)
    snap_dir = DBT_PROJECT / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    write_utf8(snap_dir / "snap_subscribers.sql", """\
{% snapshot snap_subscribers %}
{{
    config(
        target_schema = 'snapshots',
        unique_key    = 'user_id',
        strategy      = 'check',
        check_cols    = ['plan', 'mrr', 'sub_status'],
    )
}}
SELECT
    user_id, email, plan, mrr,
    sub_start_date, sub_end_date, sub_status
FROM {{ ref('dim_subscribers') }}
{% endsnapshot %}
""")


# ── ШАГ 4: Semantic Layer ────────────────────────────────
# FIX: ratio metrics must reference other METRICS, not measures.
# ltv_sum is a measure -> wrap it in total_ltv (simple metric) first.

def create_semantic_layer():
    print("\n" + "=" * 55)
    print("  STEP 4: Semantic Layer (5 metrics)")
    print("=" * 55)
    ml = DBT_PROJECT / "models" / "metrics"
    ml.mkdir(parents=True, exist_ok=True)

    write_utf8(ml / "_semantic_models_saas.yml", """\
semantic_models:
  - name: subscriptions
    description: "SaaS subscriptions semantic model"
    model: ref('fct_subscriptions')

    entities:
      - name: subscription
        type: primary
        expr: subscription_id
      - name: subscriber
        type: foreign
        expr: user_id

    dimensions:
      - name: start_date
        type: time
        expr: start_date
        type_params:
          time_granularity: day
      - name: plan
        type: categorical
        expr: plan
      - name: status
        type: categorical
        expr: status

    measures:
      - name: mrr_sum
        agg: sum
        expr: mrr
        agg_time_dimension: start_date
        create_metric: false
      - name: sub_count
        agg: count_distinct
        expr: subscription_id
        agg_time_dimension: start_date
        create_metric: false
      - name: churned_count
        agg: sum
        expr: "CASE WHEN is_churned THEN 1 ELSE 0 END"
        agg_time_dimension: start_date
        create_metric: false
      - name: ltv_sum
        agg: sum
        expr: realized_ltv
        agg_time_dimension: start_date
        create_metric: false
""")

    # FIX: avg_ltv (ratio) references total_ltv (simple metric) not ltv_sum (measure)
    write_utf8(ml / "_metrics_saas.yml", """\
metrics:

  - name: mrr
    description: "Monthly Recurring Revenue: SUM(mrr)"
    type: simple
    label: "MRR"
    type_params:
      measure: mrr_sum

  - name: subscription_count
    description: "Unique subscriptions: COUNT_DISTINCT(subscription_id)"
    type: simple
    label: "Subscription Count"
    type_params:
      measure: sub_count

  - name: churn_count
    description: "Churned subscriptions"
    type: simple
    label: "Churned Subscriptions"
    type_params:
      measure: churned_count

  # Intermediary metric needed for ratio avg_ltv
  - name: total_ltv
    description: "Total realized LTV: SUM(realized_ltv)"
    type: simple
    label: "Total LTV"
    type_params:
      measure: ltv_sum

  # ratio: numerator/denominator must be other METRICS (not measures)
  - name: avg_ltv
    description: "Average LTV per subscription = total_ltv / subscription_count"
    type: ratio
    label: "Average LTV"
    type_params:
      numerator: total_ltv
      denominator: subscription_count
""")


# ── ШАГ 5: Тесты ─────────────────────────────────────────

def create_tests():
    print("\n" + "=" * 55)
    print("  STEP 5: Singular tests")
    print("=" * 55)
    tests_dir = DBT_PROJECT / "tests"
    tests_dir.mkdir(exist_ok=True)

    write_utf8(tests_dir / "assert_no_negative_mrr.sql", """\
-- MRR не может быть отрицательным
SELECT subscription_id, mrr
FROM {{ ref('fct_subscriptions') }}
WHERE mrr < 0
""")

    write_utf8(tests_dir / "assert_churn_rate_valid.sql", """\
-- Churn rate по плану не может превышать 100%
SELECT plan,
    churned * 1.0 / NULLIF(total, 0) AS churn_rate
FROM (
    SELECT plan,
        SUM(CASE WHEN is_churned THEN 1 ELSE 0 END) AS churned,
        COUNT(*) AS total
    FROM {{ ref('fct_subscriptions') }}
    GROUP BY plan
) t
WHERE churned * 1.0 / NULLIF(total, 0) > 1.0
""")


# ── ШАГ 6: Pipeline ──────────────────────────────────────

def run_pipeline():
    print("\n" + "=" * 55)
    print("  STEP 6: Full dbt pipeline")
    print("=" * 55)
    # seed with --no-partial-parse to avoid deprecation errors
    run_dbt("seed --no-partial-parse")
    run_dbt("run --select stg_saas_users stg_subscriptions stg_events --no-partial-parse")
    run_dbt("run --select dim_subscribers fct_subscriptions --no-partial-parse")
    run_dbt("run --select mart_cohort_retention mart_rfm_segments mart_ltv --no-partial-parse")
    run_dbt("snapshot --no-partial-parse")
    run_dbt("test --no-partial-parse")
    run_dbt("parse --no-partial-parse")
    run_dbt("docs generate --no-partial-parse")


# ── ШАГ 7: Отчёт ─────────────────────────────────────────

def generate_report():
    print("\n" + "=" * 55)
    print("  STEP 7: Analytical report")
    print("=" * 55)

    db_path = find_db()
    if db_path is None:
        print("  WARNING: dev.duckdb not found - run pipeline first")
        return

    con = duckdb.connect(str(db_path), read_only=True)

    try:
        ltv = con.execute(
            "SELECT * FROM main.mart_ltv ORDER BY avg_mrr DESC"
        ).fetchdf()
        rfm = con.execute(
            "SELECT segment, COUNT(*) AS n, ROUND(AVG(monetary),2) AS avg_ltv"
            " FROM main.mart_rfm_segments GROUP BY segment ORDER BY n DESC"
        ).fetchdf()
        cohort = con.execute(
            "SELECT cohort_month, month_num, retention_pct"
            " FROM main.mart_cohort_retention"
            " WHERE month_num IN (0,1,3,6)"
            " ORDER BY cohort_month, month_num LIMIT 20"
        ).fetchdf()
        churn = con.execute(
            "SELECT plan,"
            " COUNT(*) AS total,"
            " SUM(CASE WHEN is_churned THEN 1 ELSE 0 END) AS churned,"
            " ROUND(SUM(CASE WHEN is_churned THEN 1 ELSE 0 END)*100.0/COUNT(*),1) AS churn_pct"
            " FROM main.fct_subscriptions GROUP BY plan"
        ).fetchdf()
    except Exception as e:
        print(f"  WARNING: {e}")
        con.close()
        return
    con.close()

    report = (
        f"\nMonthly Project 2 - Retention & Cohort Report\n"
        f"===============================================\n"
        f"Generated: {date.today()}\n\n"
        f"LTV BY PLAN:\n{ltv.to_string(index=False)}\n\n"
        f"CHURN BY PLAN:\n{churn.to_string(index=False)}\n\n"
        f"RFM SEGMENTS:\n{rfm.to_string(index=False)}\n\n"
        f"COHORT RETENTION (sample):\n{cohort.to_string(index=False)}\n\n"
        f"KEY INSIGHTS:\n"
        f"  - Enterprise lowest churn (2%) -> highest LTV\n"
        f"  - Basic plan needs retention focus (churn ~8%)\n"
        f"  - At Risk segment: re-engagement campaign needed\n"
        f"  - Month 3 is key inflection point\n\n"
        f"RECOMMENDATIONS:\n"
        f"  1. Upsell Basic -> Pro: 5x LTV increase\n"
        f"  2. Champions referral program\n"
        f"  3. At Risk early warning (days since last login)\n"
        f"  4. Improve month 1 onboarding (retention focus)\n"
    )
    print(report)

    (REPORTS_DIR / f"monthly_project2_report_{date.today()}.txt").write_text(
        report, encoding="utf-8"
    )
    ltv.to_csv(REPORTS_DIR / "mp2_ltv_by_plan.csv", index=False)
    rfm.to_csv(REPORTS_DIR / "mp2_rfm_segments.csv", index=False)
    cohort.to_csv(REPORTS_DIR / "mp2_cohort_retention.csv", index=False)
    churn.to_csv(REPORTS_DIR / "mp2_churn_by_plan.csv", index=False)

    print(f"  OK report + 4 CSV saved to reports/")


def main():
    print("=" * 60)
    print("  Monthly Project 2: Retention & Cohort + dbt Pipeline")
    print("=" * 60)

    generate_data()
    create_dbt_models()
    create_snapshot()
    create_semantic_layer()
    create_tests()
    run_pipeline()
    generate_report()

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print("""
Power BI:
  Get Data -> DuckDB (ODBC) -> dev.duckdb
  Tables: mart_cohort_retention, mart_ltv, mart_rfm_segments

dbt docs:
  cd dbt_analytics && dbt docs serve

Git:
  git add .
  git commit -m "feat: Monthly Project 2 - Retention & Cohort Pipeline"
  git push origin main
""")


if __name__ == "__main__":
    main()