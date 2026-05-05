#!/usr/bin/env python3
"""
lesson79_80.py - Days 79-80: Airbyte Self-Hosted
Zapusk: python lesson79_80.py
"""

import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date, timedelta
import random

random.seed(42)
np.random.seed(42)

PROJECT_ROOT  = Path(__file__).parent
AIRBYTE_DIR   = PROJECT_ROOT / "airbyte_setup"
DBT_PROJECT   = PROJECT_ROOT / "dbt_analytics"
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
DATA_DIR      = AIRBYTE_DIR / "data"
AIRBYTE_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


DOCKER_COMPOSE = """\
# airbyte_setup/docker-compose.yml
# Day 79: Airbyte Self-Hosted
#
# Ustanovka:
#   git clone https://github.com/airbytehq/airbyte.git --depth 1
#   cd airbyte && ./run-ab-platform.sh
# UI: http://localhost:8000
"""

CONNECTOR_FAKER = """\
{
  "connector": "Faker (Sample Data)",
  "config": {"count": 1000, "seed": 42, "always_updated": false},
  "streams": [
    {"name": "users",    "sync_mode": "full_refresh"},
    {"name": "products", "sync_mode": "full_refresh"},
    {"name": "orders",   "sync_mode": "incremental", "cursor_field": ["updated_at"]}
  ],
  "notes": "Start here — no credentials needed"
}
"""

CONNECTOR_POSTGRES = """\
{
  "connector": "PostgreSQL Source",
  "config": {
    "host": "localhost", "port": 5432,
    "database": "your_database",
    "username": "your_user", "password": "YOUR_PASSWORD",
    "schemas": ["public"],
    "replication_method": {"method": "CDC"}
  },
  "streams": [
    {"name": "orders", "sync_mode": "incremental", "cursor_field": ["updated_at"]},
    {"name": "users",  "sync_mode": "full_refresh"}
  ]
}
"""

CONNECTOR_GITHUB = """\
{
  "connector": "GitHub API",
  "config": {
    "repositories": ["your-org/analytics-engineer-roadmap"],
    "credentials": {
      "option_title": "PAT Credentials",
      "personal_access_token": "YOUR_GITHUB_PAT"
    }
  },
  "streams": [
    {"name": "commits",       "sync_mode": "incremental"},
    {"name": "pull_requests", "sync_mode": "incremental"},
    {"name": "issues",        "sync_mode": "incremental"}
  ]
}
"""

DESTINATION_SNOWFLAKE = """\
{
  "connector": "Snowflake Destination",
  "config": {
    "host":      "YOUR_ACCOUNT.snowflakecomputing.com",
    "role":      "analyst_role",
    "warehouse": "analytics_wh",
    "database":  "analytics_db",
    "schema":    "raw",
    "username":  "YOUR_USERNAME",
    "password":  "YOUR_PASSWORD"
  },
  "normalization": "basic"
}
"""

AIRBYTE_README = """\
# Airbyte Self-Hosted — Days 79-80

## Quick Install
```bash
git clone https://github.com/airbytehq/airbyte.git --depth 1
cd airbyte && ./run-ab-platform.sh
# Open http://localhost:8000
```

## 3 Connectors

### 1. Faker (start here — no credentials)
Sources -> New Source -> Faker -> Count: 1000, Seed: 42

### 2. GitHub API
Sources -> New Source -> GitHub
Personal Access Token: github.com -> Settings -> Developer Settings -> PAT

### 3. PostgreSQL
Sources -> New Source -> PostgreSQL -> CDC replication

## Destination: Snowflake
See connectors/04_snowflake_destination.json

## After sync
```sql
SHOW TABLES IN SCHEMA analytics_db.raw;
SELECT * FROM analytics_db.raw._airbyte_raw_orders LIMIT 10;
```
"""

STG_AIRBYTE_ORDERS_SQL = """\
-- models/staging/stg_airbyte_orders.sql
-- Day 80: Normalizatsiya Airbyte dannykh cherez dbt
-- [[Airbyte]] [[Snowflake]]

{{
    config(materialized='view', tags=['airbyte', 'staging'])
}}

WITH raw AS (
    SELECT
        _airbyte_data:id::INTEGER      AS order_id,
        _airbyte_data:user_id::INTEGER AS user_id,
        _airbyte_data:amount::FLOAT    AS amount,
        _airbyte_data:status::VARCHAR  AS status,
        _airbyte_data:city::VARCHAR    AS city,
        _airbyte_data:order_date::DATE AS order_date,
        _airbyte_extracted_at          AS airbyte_extracted_at
    FROM {{ source('airbyte_raw', '_airbyte_raw_orders') }}
    WHERE _airbyte_data IS NOT NULL
)
SELECT
    order_id, user_id,
    ROUND(amount, 2) AS amount,
    LOWER(status)    AS status,
    UPPER(city)      AS city,
    order_date, airbyte_extracted_at
FROM raw
WHERE order_id IS NOT NULL AND amount > 0
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY order_id ORDER BY airbyte_extracted_at DESC
) = 1
"""

STG_AIRBYTE_GITHUB_SQL = """\
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
"""

SOURCES_AIRBYTE_YML = """\
version: 2
sources:
  - name: airbyte_raw
    description: "Dannye zagruzhennye Airbyte v Snowflake raw schema"
    database: analytics_db
    schema: raw
    tables:
      - name: _airbyte_raw_orders
      - name: _airbyte_raw_users
      - name: _airbyte_raw_commits
      - name: _airbyte_raw_pull_requests
"""


def generate_airbyte_csv():
    """Pishem CSV fayly kak budet pisat Airbyte v Stage."""
    print("\n  Generating simulated Airbyte CSV files...")

    cities   = ["MOSCOW", "SPB", "KAZAN", "NOVOSIBIRSK"]
    statuses = ["completed", "pending", "cancelled"]
    n = 500

    rows = []
    for i in range(1, n + 1):
        rows.append({
            "_airbyte_ab_id":         f"ab_{i:06d}",
            "_airbyte_extracted_at":  "2026-04-28T10:05:00Z",
            "id":         i,
            "user_id":    random.randint(1, 101),
            "amount":     round(random.uniform(10, 5000), 2),
            "status":     random.choice(statuses),
            "city":       random.choice(cities),
            "order_date": str(date(2024, 1, 1) + timedelta(days=random.randint(0, 364))),
        })
    pd.DataFrame(rows).to_csv(DATA_DIR / "airbyte_raw_orders.csv", index=False)
    print(f"  OK airbyte_setup/data/airbyte_raw_orders.csv ({n} rows)")

    authors  = ["alice@dev.com", "bob@dev.com", "carol@dev.com"]
    messages = ["feat: new model", "fix: schema bug", "docs: update", "chore: cleanup"]
    commits = []
    for i in range(1, 51):
        commits.append({
            "sha":          f"abc{i:04d}",
            "author":       random.choice(authors),
            "message":      random.choice(messages),
            "committed_at": str(date(2026, 1, 1) + timedelta(days=random.randint(0, 120))),
        })
    pd.DataFrame(commits).to_csv(DATA_DIR / "airbyte_raw_commits.csv", index=False)
    print(f"  OK airbyte_setup/data/airbyte_raw_commits.csv (50 rows)")


def simulate_airbyte_pipeline():
    """Chitaem CSV cherez read_csv_auto — bez register, bez DataFrame v execute."""
    print("\n  Simulating Airbyte pipeline via DuckDB (read_csv_auto)...")

    orders_csv  = str(DATA_DIR / "airbyte_raw_orders.csv")
    commits_csv = str(DATA_DIR / "airbyte_raw_commits.csv")
    db_path     = str(SNOWFLAKE_DIR / "snowflake_simulation.duckdb")

    con = duckdb.connect(db_path)

    for schema in ("raw", "staging"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # COPY INTO raw.airbyte_raw_orders
    con.execute("DROP TABLE IF EXISTS raw.airbyte_raw_orders")
    con.execute(f"""
        CREATE TABLE raw.airbyte_raw_orders AS
        SELECT
            CAST(_airbyte_ab_id        AS VARCHAR) AS _airbyte_ab_id,
            CAST(_airbyte_extracted_at AS VARCHAR) AS _airbyte_extracted_at,
            CAST(id                    AS INTEGER) AS id,
            CAST(user_id               AS INTEGER) AS user_id,
            CAST(amount                AS DOUBLE)  AS amount,
            CAST(status                AS VARCHAR) AS status,
            CAST(city                  AS VARCHAR) AS city,
            CAST(order_date            AS DATE)    AS order_date
        FROM read_csv_auto('{orders_csv}', header=true)
    """)

    # COPY INTO raw.airbyte_raw_commits
    con.execute("DROP TABLE IF EXISTS raw.airbyte_raw_commits")
    con.execute(f"""
        CREATE TABLE raw.airbyte_raw_commits AS
        SELECT
            CAST(sha          AS VARCHAR) AS sha,
            CAST(author       AS VARCHAR) AS author,
            CAST(message      AS VARCHAR) AS message,
            CAST(committed_at AS DATE)    AS committed_at
        FROM read_csv_auto('{commits_csv}', header=true)
    """)

    # Normalization (analog stg_airbyte_orders.sql)
    con.execute("DROP TABLE IF EXISTS staging.stg_airbyte_orders")
    con.execute("""
        CREATE TABLE staging.stg_airbyte_orders AS
        SELECT
            id               AS order_id,
            user_id,
            ROUND(amount, 2) AS amount,
            LOWER(status)    AS status,
            UPPER(city)      AS city,
            order_date
        FROM raw.airbyte_raw_orders
        WHERE amount > 0 AND id IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY id ORDER BY _airbyte_extracted_at DESC
        ) = 1
    """)

    cnt = con.execute(
        "SELECT COUNT(*) FROM staging.stg_airbyte_orders"
    ).fetchone()[0]
    print(f"\n  stg_airbyte_orders: {cnt} rows (after dedup + filter)")

    print("\n  Revenue by city (Airbyte data):")
    print(con.execute("""
        SELECT city,
            ROUND(SUM(amount), 2) AS revenue,
            COUNT(*) AS orders
        FROM staging.stg_airbyte_orders
        WHERE status = 'completed'
        GROUP BY city ORDER BY revenue DESC
    """).df().to_string(index=False))

    commits_cnt = con.execute(
        "SELECT COUNT(*) FROM raw.airbyte_raw_commits"
    ).fetchone()[0]
    print(f"\n  GitHub commits loaded: {commits_cnt}")

    print("\n  Commits by author:")
    print(con.execute("""
        SELECT author, COUNT(*) AS commits
        FROM raw.airbyte_raw_commits
        GROUP BY author ORDER BY commits DESC
    """).df().to_string(index=False))

    con.close()
    print("\n  OK Airbyte simulation complete")


def main():
    print("=" * 60)
    print("  Days 79-80: Airbyte Self-Hosted")
    print("=" * 60)

    print("\n[1/4] Creating Airbyte setup files...")
    write_utf8(AIRBYTE_DIR / "docker-compose.yml",                          DOCKER_COMPOSE)
    write_utf8(AIRBYTE_DIR / "connectors" / "01_faker.json",                CONNECTOR_FAKER)
    write_utf8(AIRBYTE_DIR / "connectors" / "02_postgres.json",             CONNECTOR_POSTGRES)
    write_utf8(AIRBYTE_DIR / "connectors" / "03_github.json",               CONNECTOR_GITHUB)
    write_utf8(AIRBYTE_DIR / "connectors" / "04_snowflake_destination.json",DESTINATION_SNOWFLAKE)
    write_utf8(AIRBYTE_DIR / "README.md",                                    AIRBYTE_README)

    print("\n[2/4] Creating dbt normalization models...")
    write_utf8(DBT_PROJECT / "models" / "staging" / "stg_airbyte_orders.sql",
               STG_AIRBYTE_ORDERS_SQL)
    write_utf8(DBT_PROJECT / "models" / "staging" / "stg_airbyte_github_commits.sql",
               STG_AIRBYTE_GITHUB_SQL)
    write_utf8(DBT_PROJECT / "models" / "staging" / "sources_airbyte.yml",
               SOURCES_AIRBYTE_YML)

    print("\n[3/4] Simulating Airbyte pipeline...")
    generate_airbyte_csv()
    simulate_airbyte_pipeline()

    print("\n[4/4] Checkpoint...")
    print("""
  [OK] docker-compose.yml + 3 connector configs
  [OK] Snowflake destination config
  [OK] dbt normalization models (stg_airbyte_*)
  [OK] DuckDB simulation: Airbyte raw -> staging pipeline
    """)

    print("=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print("""
Airbyte setup:
  1. git clone https://github.com/airbytehq/airbyte.git --depth 1
  2. cd airbyte && ./run-ab-platform.sh
  3. Open http://localhost:8000
  4. Source: Faker -> Destination: Snowflake -> Sync

After sync in dbt:
  dbt run --select stg_airbyte_orders --target snowflake_dev

Git:
  git add airbyte_setup/ dbt_analytics/models/ lesson79_80.py
  git commit -m "feat: Days 79-80 Airbyte self-hosted + dbt normalization"
  git push origin main
""")


if __name__ == "__main__":
    main()