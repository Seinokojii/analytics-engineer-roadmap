#!/usr/bin/env python3
"""
lesson76_78.py - Days 76-78: dbt + Snowflake
Zapusk: python lesson76_78.py
"""

import subprocess
import duckdb
from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent
DBT_PROJECT   = PROJECT_ROOT / "dbt_analytics"
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
SNOWFLAKE_DIR.mkdir(exist_ok=True)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = path
    print(f"  OK {rel}")


def run_dbt(cmd: str) -> bool:
    print(f"\n> dbt {cmd}")
    r = subprocess.run(
        f"dbt {cmd}", shell=True, cwd=DBT_PROJECT,
        capture_output=True, text=True, encoding="utf-8"
    )
    for line in r.stdout.strip().split("\n")[-5:]:
        print(line)
    if r.returncode != 0:
        print(f"WARNING: {r.stderr[-200:]}")
    return r.returncode == 0


PROFILES_SNOWFLAKE = """\
# profiles_snowflake_template.yml
# Dobav etot blok v ~/.dbt/profiles.yml

analytics:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "dev.duckdb"
      threads: 4
    snowflake_dev:
      type: snowflake
      account:   YOUR_ACCOUNT_IDENTIFIER
      user:      YOUR_USERNAME
      password:  YOUR_PASSWORD
      role:      analyst_role
      database:  analytics_db
      warehouse: analytics_wh
      schema:    staging
      threads:   4
      client_session_keep_alive: false
    snowflake_prod:
      type: snowflake
      account:   YOUR_ACCOUNT_IDENTIFIER
      user:      YOUR_SERVICE_ACCOUNT_USER
      password:  YOUR_PASSWORD
      role:      analyst_role
      database:  analytics_db
      warehouse: analytics_wh
      schema:    marts
      threads:   8
      client_session_keep_alive: false
"""

FCT_ORDERS_INCREMENTAL_SQL = """\
-- models/marts/fct_orders_incremental.sql
-- Day 76: Incremental model na Snowflake, strategy: merge

{{
    config(
        materialized         = 'incremental',
        unique_key           = 'order_id',
        incremental_strategy = 'merge',
        cluster_by           = ['order_date'],
        on_schema_change     = 'sync_all_columns',
    )
}}

SELECT
    o.order_id,
    o.user_id,
    o.city,
    o.amount,
    o.order_date
FROM {{ ref('stg_orders') }} o

{% if is_incremental() %}
    WHERE o.order_date >= (
        SELECT DATEADD('day', -3, MAX(order_date)) FROM {{ this }}
    )
{% endif %}
"""

FCT_ORDERS_APPEND_SQL = """\
-- models/marts/fct_orders_append.sql
-- Day 76: Incremental append — tolko INSERT

{{
    config(
        materialized         = 'incremental',
        unique_key           = 'order_id',
        incremental_strategy = 'append',
    )
}}

SELECT order_id, user_id, amount, city, order_date
FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
    WHERE order_date > (SELECT MAX(order_date) FROM {{ this }})
{% endif %}
"""

DIM_CUSTOMERS_CLUSTERED_SQL = """\
-- models/marts/dim_customers_clustered.sql
-- Day 77: Clustering Key po city

{{
    config(
        materialized = 'table',
        cluster_by   = ['city'],
    )
}}

SELECT
    u.user_id, u.email, u.city, u.channel,
    COUNT(o.order_id)       AS total_orders,
    ROUND(SUM(o.amount), 2) AS total_spent,
    ROUND(AVG(o.amount), 2) AS avg_order_value,
    MAX(o.order_date)       AS last_order_date
FROM {{ ref('stg_users') }} u
LEFT JOIN {{ ref('stg_orders') }} o ON u.user_id = o.user_id
GROUP BY u.user_id, u.email, u.city, u.channel
"""

SCHEMA_SNOWFLAKE_YML = """\
version: 2
models:
  - name: fct_orders_incremental
    description: "Incremental fct_orders s merge strategy"
    columns:
      - name: order_id
        data_tests: [not_null, unique]
      - name: amount
        data_tests: [not_null]

  - name: dim_customers_clustered
    description: "dim_customers s Clustering Key po city"
    columns:
      - name: user_id
        data_tests: [not_null, unique]
"""

SNOWFLAKE_RUN_SQL = """\
-- snowflake_setup/08_dbt_snowflake_commands.sql
-- pip install dbt-snowflake
-- dbt debug --target snowflake_dev
-- dbt run --target snowflake_dev
-- dbt run --select fct_orders_incremental --target snowflake_dev
-- dbt run --select fct_orders_incremental --full-refresh --target snowflake_dev
-- dbt test --target snowflake_dev

-- Proverit clustering v Snowflake:
-- SELECT SYSTEM$CLUSTERING_INFORMATION(
--     'analytics_db.marts.dim_customers_clustered', '(city)'
-- );
"""


def simulate_snowflake_incremental():
    print("\n  Simulating Snowflake incremental (merge) via DuckDB...")

    orders_csv = str(SNOWFLAKE_DIR / "data" / "orders.csv")
    users_csv  = str(SNOWFLAKE_DIR / "data" / "users.csv")

    if not Path(orders_csv).exists():
        print("  WARNING: Run lesson74_75.py first to generate CSV data")
        return

    db_path = str(SNOWFLAKE_DIR / "snowflake_simulation.duckdb")
    con = duckdb.connect(db_path)

    for schema in ("raw", "staging", "marts"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    con.execute("DROP TABLE IF EXISTS staging.stg_orders")
    con.execute(f"""
        CREATE TABLE staging.stg_orders AS
        SELECT
            CAST(order_id   AS INTEGER) AS order_id,
            CAST(user_id    AS INTEGER) AS user_id,
            CAST(amount     AS DOUBLE)  AS amount,
            CAST(city       AS VARCHAR) AS city,
            CAST(order_date AS DATE)    AS order_date
        FROM read_csv_auto('{orders_csv}', header=true)
        WHERE status = 'completed' AND amount > 0
    """)

    con.execute("DROP TABLE IF EXISTS staging.stg_users")
    con.execute(f"""
        CREATE TABLE staging.stg_users AS
        SELECT
            CAST(user_id  AS INTEGER) AS user_id,
            CAST(email    AS VARCHAR) AS email,
            CAST(city     AS VARCHAR) AS city,
            CAST(channel  AS VARCHAR) AS channel
        FROM read_csv_auto('{users_csv}', header=true)
    """)

    # Full load (pervyy zapusk)
    con.execute("DROP TABLE IF EXISTS marts.fct_orders_incremental")
    con.execute("""
        CREATE TABLE marts.fct_orders_incremental AS
        SELECT order_id, user_id, city, amount, order_date
        FROM staging.stg_orders
        WHERE order_date < '2024-07-01'
    """)
    cnt1 = con.execute(
        "SELECT COUNT(*) FROM marts.fct_orders_incremental"
    ).fetchone()[0]
    print(f"\n  [Full load] fct_orders_incremental: {cnt1} rows")

    # Incremental: simulate merge via DELETE + INSERT (DuckDB net PRIMARY KEY)
    # V Snowflake eto MERGE INTO ... WHEN MATCHED THEN UPDATE / WHEN NOT MATCHED THEN INSERT
    con.execute("""
        DELETE FROM marts.fct_orders_incremental
        WHERE order_id IN (
            SELECT order_id FROM staging.stg_orders
            WHERE order_date >= '2024-07-01'
        )
    """)
    con.execute("""
        INSERT INTO marts.fct_orders_incremental
        SELECT order_id, user_id, city, amount, order_date
        FROM staging.stg_orders
        WHERE order_date >= '2024-07-01'
    """)
    cnt2 = con.execute(
        "SELECT COUNT(*) FROM marts.fct_orders_incremental"
    ).fetchone()[0]
    print(f"  [Incremental merge] fct_orders_incremental: {cnt2} rows (+{cnt2-cnt1})")

    # dim_customers clustered (ORDER BY = clustering proxy v DuckDB)
    con.execute("DROP TABLE IF EXISTS marts.dim_customers_clustered")
    con.execute("""
        CREATE TABLE marts.dim_customers_clustered AS
        SELECT
            u.user_id, u.email, u.city, u.channel,
            COUNT(o.order_id)       AS total_orders,
            ROUND(SUM(o.amount), 2) AS total_spent,
            ROUND(AVG(o.amount), 2) AS avg_order_value
        FROM staging.stg_users u
        LEFT JOIN staging.stg_orders o ON u.user_id = o.user_id
        GROUP BY u.user_id, u.email, u.city, u.channel
        ORDER BY u.city
    """)
    print("\n  [Clustering sim] dim_customers_clustered by city:")
    print(con.execute("""
        SELECT city, COUNT(*) AS customers, ROUND(AVG(total_spent), 2) AS avg_ltv
        FROM marts.dim_customers_clustered
        GROUP BY city ORDER BY avg_ltv DESC
    """).df().to_string(index=False))

    con.close()
    print("\n  OK Snowflake incremental simulation complete")


def main():
    print("=" * 60)
    print("  Days 76-78: dbt + Snowflake")
    print("=" * 60)

    print("\n[1/4] Installing dbt-snowflake...")
    r = subprocess.run(
        "pip install dbt-snowflake --quiet",
        shell=True, capture_output=True, text=True
    )
    print("  OK dbt-snowflake installed" if r.returncode == 0
          else f"  WARNING: {r.stderr[-100:]}")

    print("\n[2/4] Creating files...")
    write_utf8(SNOWFLAKE_DIR / "profiles_snowflake_template.yml", PROFILES_SNOWFLAKE)
    write_utf8(DBT_PROJECT / "models" / "marts" / "fct_orders_incremental.sql",
               FCT_ORDERS_INCREMENTAL_SQL)
    write_utf8(DBT_PROJECT / "models" / "marts" / "fct_orders_append.sql",
               FCT_ORDERS_APPEND_SQL)
    write_utf8(DBT_PROJECT / "models" / "marts" / "dim_customers_clustered.sql",
               DIM_CUSTOMERS_CLUSTERED_SQL)
    write_utf8(DBT_PROJECT / "models" / "marts" / "schema_snowflake.yml",
               SCHEMA_SNOWFLAKE_YML)
    write_utf8(SNOWFLAKE_DIR / "08_dbt_snowflake_commands.sql", SNOWFLAKE_RUN_SQL)

    print("\n[3/4] Running dbt (local DuckDB target)...")
    run_dbt("run --select fct_orders_incremental --no-partial-parse")
    run_dbt("test --select fct_orders_incremental --no-partial-parse")

    print("\n[4/4] Simulating Snowflake incremental...")
    simulate_snowflake_incremental()

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print("""
Snowflake steps:
  1. Copy snowflake_setup/profiles_snowflake_template.yml
     -> add snowflake_dev block to ~/.dbt/profiles.yml
  2. cd dbt_analytics && dbt debug --target snowflake_dev
  3. dbt run --target snowflake_dev
  4. dbt run --select fct_orders_incremental --target snowflake_dev

Git:
  git add dbt_analytics/models/marts/ snowflake_setup/ lesson76_78.py
  git commit -m "feat: Days 76-78 dbt + Snowflake incremental + clustering"
  git push origin main
""")


if __name__ == "__main__":
    main()