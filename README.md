# Analytics Engineer Portfolio — Diyar Mahmudov

Junior Analytics Engineer, Bishkek (UTC+6). Six projects built over 96 days of
deliberate practice: **SQL · dbt · Snowflake · Dagster · Airbyte · DuckDB**.

Looking for an internship or part-time role, remote.

**[Live dashboard](https://seinokojii.github.io/analytics-engineer-roadmap/)** ·
[Production pipeline docs](docs/PRODUCTION_PIPELINE.md) ·
[dbt CI](https://github.com/Seinokojii/analytics-engineer-roadmap/actions/workflows/dbt_ci.yml)

[![dbt CI](https://github.com/Seinokojii/analytics-engineer-roadmap/actions/workflows/dbt_ci.yml/badge.svg)](https://github.com/Seinokojii/analytics-engineer-roadmap/actions/workflows/dbt_ci.yml)

---

## The one project to read first

### Production Pipeline — Airbyte pattern → dbt → Dagster → quality gate

An end-to-end pipeline that is reproducible from a clean checkout. Not "I can
write dbt models" but "I can make a pipeline fail loudly and rebuild itself on
someone else's machine".

```mermaid
flowchart LR
    CSV["gh_events.csv<br/>source system"]

    subgraph INGEST["Ingest — Airbyte pattern"]
        RAW[("raw.airbyte_raw_gh_events<br/>JSON payload + metadata")]
    end

    subgraph TRANSFORM["dbt"]
        STG["stg_gh_events<br/>view<br/>flatten · filter · dedupe"]
        M1["mart_daily_events<br/>incremental<br/>delete+insert by date"]
        M2["mart_repo_activity<br/>table"]
    end

    subgraph QUALITY["Quality"]
        AC["Dagster asset checks<br/>not empty · freshness"]
        T["26 dbt tests<br/>16 core + 10 expectations"]
        EL["Elementary<br/>4 anomaly tests, 7 metrics"]
    end

    CSV --> RAW --> STG
    STG --> M1
    STG --> M2
    RAW -.-> AC
    M1 -.-> T
    M2 -.-> T
    STG -.-> EL
```

| | |
|---|---|
| **Stack** | Dagster · dbt Core · DuckDB (Snowflake by changing a target) · Elementary |
| **Scale** | 3 daily partitions, 227 events, 3 dbt models |
| **Tests** | 30 across three layers — `dbt build` PASS=35, ERROR=0 |
| **CI** | 2 jobs per pull request, both green on PR #1 (parse 39s, build 1m) |
| **Docs** | `dbt docs` with 25/25 columns described; Dagster asset catalog |
| **Run it** | `docker compose up` → Dagster on `:3000` |

The test suite is verified *negatively*: a script corrupts the raw table on
purpose, asserts the tests go red, then restores the database. A test suite
that has never failed is an unverified test suite.

→ **[Full documentation, quick start, and the Snowflake migration path](docs/PRODUCTION_PIPELINE.md)**
· code in [`production_pipeline/`](production_pipeline/) and [`dbt_analytics/`](dbt_analytics/)

**What I would improve:** ingestion reads one source through the Airbyte
*pattern* rather than a running Airbyte instance — the three real connectors
live in [`airbyte_setup/`](airbyte_setup/) but are not wired into the Dagster
graph. Backfill is proven by re-running partitions from code; I have not driven
it from the Dagster UI.

---

## SaaS Subscriptions — retention, churn, cohorts

A subscription analytics stack: 500 users, 800 subscriptions, 8 dbt models
across staging and marts, SCD Type 2 snapshots, MetricFlow semantic layer.

**[→ Open the dashboard](https://seinokojii.github.io/analytics-engineer-roadmap/)**
— MRR, churn by plan, churn by acquisition channel, revenue mix. Every number
on the page expands to the SQL that produced it.

```mermaid
flowchart LR
    S1[raw_saas_users] --> ST[staging<br/>3 models]
    S2[raw_subscriptions] --> ST
    S3[raw_events] --> ST
    ST --> D[dim_subscribers<br/>SCD Type 2]
    ST --> F[fct_subscriptions<br/>MRR · churn · lifetime]
    F --> C[mart_cohort_retention]
    F --> R[mart_rfm_segments]
    F --> L[mart_ltv]
    F --> M[MetricFlow<br/>5 metrics]
```

**The finding that matters more than the models.** While building the
dashboard I checked the cohort table against the raw data and found retention
that *grows* month over month — 11 → 32 → 51 → 71 users in the January cohort,
which is impossible. Cause: subscription `start_date` is generated
independently of user `signup_date`, so the dataset carries no temporal link
between signup and subscription. Cohort retention and survival-based LTV cannot
be computed from it at all, and the shipped `cohort_analysis` table hid this
behind rows with a negative "months since signup".

The dashboard therefore shows churn, which the data supports, and states the
limitation on the page instead of drawing a curve that would look fine and mean
nothing.

**What I would improve:** replace the generator so subscription dates derive
from signup dates with a rising churn hazard, and add a `start_date >=
signup_date` test — one rule would have caught this on the first run.

→ code in [`dbt_analytics/models/`](dbt_analytics/models/)

---

## E-commerce Data Warehouse — star schema from raw CSV

Python OOP ETL → DuckDB warehouse → dbt models → KPI dashboard. Built on a
deliberately dirty dataset: 100 duplicate orders, 5% NULLs in `channel` and
`payment`, and foreign keys pointing outside the product dimension.

```mermaid
flowchart LR
    C1[products.csv] --> E[ETL — Python OOP<br/>extract · dedupe · enrich]
    C2[customers.csv] --> E
    C3[orders.csv] --> E
    E --> W[(DuckDB)]
    W --> FO[fct_orders<br/>5 000 rows]
    W --> DC[dim_customers · 500]
    W --> DP[dim_products · 25]
    W --> DD[dim_date · 365]
    W --> DCH[dim_channels]
```

| | |
|---|---|
| **Model** | Star schema — 1 fact, 4 dimensions |
| **Volume** | 5 000 orders, 500 customers, 365 days |
| **Quality** | Deduplication, NULL policy per column, referential checks |
| **Output** | Two matplotlib dashboards, KPI report |

**What I would improve:** 3 748 of 5 000 orders carry a zero price because
`product_id` in the source ranges beyond the 25 products in the dimension, so
the merge produces NULLs that the ETL fills with zero. Filling with zero was
the wrong call — those rows should be quarantined into a reject table and
counted, not silently averaged into revenue. That is why this project's
numbers are not on the dashboard.

→ code in [`project/`](project/)

---

## Three focused builds

| Project | What it demonstrates | Code |
|---|---|---|
| **Data contracts** | Schema contracts as YAML with enforced types and constraints; a breaking change fails CI before merge | [`contracts/`](contracts/) |
| **Semantic layer** | 5 MetricFlow metrics defined once, queried consistently; a metrics API over them | [`dbt_analytics/metrics/`](dbt_analytics/metrics/) · [`metrics_api/`](metrics_api/) |
| **Snowflake architecture** | RBAC, stages, `COPY INTO`, Streams, Tasks, Time Travel, zero-copy clone — 14 SQL scripts | [`snowflake_setup/`](snowflake_setup/) |

**Honest limitation on the Snowflake work:** the scripts are written against
real Snowflake syntax but have not been executed on a Snowflake account — the
mechanics were reproduced locally in DuckDB (a `valid_from`/`valid_to` history
table for Time Travel, an offset-and-hash diff for Streams). `UNDROP` and
Fail-safe cannot be simulated locally, and I say so rather than implying
production experience.

---

## Stack

| | |
|---|---|
| **Languages** | SQL (advanced), Python (pandas, Polars, requests, OOP) |
| **Transformation** | dbt Core — models, tests, macros, snapshots, incremental, packages, semantic layer |
| **Warehouse** | Snowflake (scripts), PostgreSQL, DuckDB |
| **Orchestration** | Dagster — assets, schedules, sensors, partitions, backfill, asset checks |
| **Ingestion** | Airbyte self-hosted, 3 connectors |
| **Quality & CI** | dbt tests, dbt-expectations, Elementary, data contracts, GitHub Actions |
| **BI** | Metabase, Lightdash, matplotlib |

---

## Repository layout

| Path | Contents |
|---|---|
| `production_pipeline/` | Dagster assets, checks, schedule |
| `dbt_analytics/` | dbt models, tests, macros, metrics |
| `project/` | E-commerce warehouse + ETL |
| `contracts/` | Data contracts |
| `snowflake_setup/` | Snowflake SQL scripts |
| `airbyte_setup/` | Connector configuration |
| `docs/` | Pipeline documentation, dashboard, demo script |
| `lesson*.py` | Daily exercises, days 1–96 |

<details>
<summary>About the lesson files</summary>

This repository doubles as a 180-day Analytics Engineer study roadmap. The
`lesson*.py` files are daily exercises; the projects above are what they build
up to. They are kept in the open on purpose — the working notes are part of the
evidence.

</details>
