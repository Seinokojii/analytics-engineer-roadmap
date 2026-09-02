#!/usr/bin/env python3
"""
lesson74_75.py - Days 74-75: Snowflake Data Loading
Запуск: python lesson74_75.py
"""

import pandas as pd
import numpy as np
import duckdb
from pathlib import Path
from datetime import date, timedelta
import random

random.seed(42)
np.random.seed(42)

PROJECT_ROOT  = Path(__file__).parent
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
DATA_DIR      = SNOWFLAKE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


STAGE_SQL = """\
-- snowflake_setup/06_stage_copy_into.sql
-- Day 74: Stage + COPY INTO

USE ROLE analyst_role;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

CREATE STAGE IF NOT EXISTS raw.orders_stage
    FILE_FORMAT = (
        TYPE = 'CSV' FIELD_DELIMITER = ','
        SKIP_HEADER = 1
        NULL_IF = ('NULL', 'null', '')
        EMPTY_FIELD_AS_NULL = TRUE
    );

-- PUT file://./snowflake_setup/data/orders.csv @raw.orders_stage;
-- PUT file://./snowflake_setup/data/users.csv  @raw.orders_stage;

LIST @raw.orders_stage;

COPY INTO raw.orders (order_id, user_id, amount, status, city, order_date)
FROM @raw.orders_stage/orders.csv
FILE_FORMAT = (TYPE='CSV' FIELD_DELIMITER=',' SKIP_HEADER=1)
ON_ERROR = 'CONTINUE';

SELECT COUNT(*), MIN(order_date), MAX(order_date) FROM raw.orders;

COPY INTO raw.users (user_id, email, city, channel, created_at)
FROM @raw.orders_stage/users.csv
FILE_FORMAT = (TYPE='CSV' FIELD_DELIMITER=',' SKIP_HEADER=1)
ON_ERROR = 'CONTINUE';
"""

STREAMS_SQL = """\
-- snowflake_setup/07_streams_cdc.sql
-- Day 74: Streams CDC

USE ROLE analyst_role;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

CREATE STREAM IF NOT EXISTS raw.orders_stream
    ON TABLE raw.orders
    COMMENT = 'CDC stream: изменения в raw.orders';

SELECT * FROM raw.orders_stream LIMIT 10;

CREATE TASK IF NOT EXISTS raw.process_new_orders
    WAREHOUSE = analytics_wh
    SCHEDULE  = '5 MINUTE'
WHEN
    SYSTEM$STREAM_HAS_DATA('raw.orders_stream')
AS
    INSERT INTO staging.stg_orders (order_id, user_id, amount, city, order_date)
    SELECT order_id, user_id, amount, city, order_date
    FROM raw.orders_stream
    WHERE METADATA$ACTION = 'INSERT' AND status = 'completed';

ALTER TASK raw.process_new_orders RESUME;
"""

SNOWSQL_CONFIG = """\
# snowflake_setup/snowsql_config.txt
# ~/.snowsql/config

[connections.analytics]
accountname   = YOUR_ACCOUNT_IDENTIFIER
username      = YOUR_USERNAME
password      = YOUR_PASSWORD
dbname        = analytics_db
schemaname    = raw
warehousename = analytics_wh
rolename      = analyst_role

# snowsql -c analytics
# snowsql -c analytics -f snowflake_setup/06_stage_copy_into.sql
"""

DBT_PROFILE_SNOWFLAKE = """\
# snowflake_setup/profiles_snowflake.yml
# Добавь в ~/.dbt/profiles.yml:
#
# analytics:
#   outputs:
#     snowflake:
#       type:      snowflake
#       account:   YOUR_ACCOUNT
#       user:      YOUR_USERNAME
#       password:  YOUR_PASSWORD
#       role:      analyst_role
#       database:  analytics_db
#       warehouse: analytics_wh
#       schema:    marts
#       threads:   4
#
# pip install dbt-snowflake
# dbt debug --target snowflake
"""


def generate_csv_data():
    print("\n  Generating CSV files...")
    cities   = ["MOSCOW", "SPB", "KAZAN", "NOVOSIBIRSK", "YEKATERINBURG"]
    statuses = ["completed", "pending", "cancelled"]
    n, m = 1000, 200

    pd.DataFrame({
        "order_id":   range(1, n + 1),
        "user_id":    np.random.randint(1, m + 1, n),
        "amount":     np.round(np.random.uniform(10, 5000, n), 2),
        "status":     np.random.choice(statuses, n, p=[0.7, 0.2, 0.1]),
        "city":       np.random.choice(cities, n),
        "order_date": [
            str(date(2024, 1, 1) + timedelta(days=random.randint(0, 364)))
            for _ in range(n)
        ],
    }).to_csv(DATA_DIR / "orders.csv", index=False)
    print(f"  OK data/orders.csv ({n} rows)")

    pd.DataFrame({
        "user_id":    range(1, m + 1),
        "email":      [f"user{i}@example.com" for i in range(1, m + 1)],
        "city":       np.random.choice(cities, m),
        "channel":    np.random.choice(
            ["organic", "paid", "referral", "social"], m, p=[0.4, 0.3, 0.2, 0.1]
        ),
        "created_at": [
            str(date(2023, 1, 1) + timedelta(days=random.randint(0, 364)))
            for _ in range(m)
        ],
    }).to_csv(DATA_DIR / "users.csv", index=False)
    print(f"  OK data/users.csv ({m} rows)")


def simulate_copy_into() -> None:
    """Читаем прямо из CSV через DuckDB read_csv_auto — без register."""
    print("\n  Simulating COPY INTO via DuckDB (read_csv_auto)...")

    orders_csv = str(DATA_DIR / "orders.csv")
    users_csv  = str(DATA_DIR / "users.csv")
    db_path    = str(SNOWFLAKE_DIR / "snowflake_simulation.duckdb")

    con = duckdb.connect(db_path)

    for schema in ("raw", "staging", "marts"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # COPY INTO raw.orders — читаем из CSV напрямую
    con.execute("DROP TABLE IF EXISTS raw.orders")
    con.execute(f"""
        CREATE TABLE raw.orders AS
        SELECT
            CAST(order_id   AS INTEGER) AS order_id,
            CAST(user_id    AS INTEGER) AS user_id,
            CAST(amount     AS DOUBLE)  AS amount,
            CAST(status     AS VARCHAR) AS status,
            CAST(city       AS VARCHAR) AS city,
            CAST(order_date AS DATE)    AS order_date,
            NOW()                       AS loaded_at
        FROM read_csv_auto('{orders_csv}', header=true)
    """)

    # COPY INTO raw.users
    con.execute("DROP TABLE IF EXISTS raw.users")
    con.execute(f"""
        CREATE TABLE raw.users AS
        SELECT
            CAST(user_id    AS INTEGER) AS user_id,
            CAST(email      AS VARCHAR) AS email,
            CAST(city       AS VARCHAR) AS city,
            CAST(channel    AS VARCHAR) AS channel,
            CAST(created_at AS DATE)    AS created_at
        FROM read_csv_auto('{users_csv}', header=true)
    """)

    # Staging
    con.execute("DROP TABLE IF EXISTS staging.stg_orders")
    con.execute("""
        CREATE TABLE staging.stg_orders AS
        SELECT order_id, user_id, amount, city, order_date
        FROM raw.orders
        WHERE status = 'completed' AND amount > 0
    """)

    # Marts
    con.execute("DROP TABLE IF EXISTS marts.fct_orders")
    con.execute("""
        CREATE TABLE marts.fct_orders AS
        SELECT o.order_id, o.user_id, u.email,
               o.city, u.channel, o.amount, o.order_date
        FROM staging.stg_orders o
        LEFT JOIN raw.users u ON o.user_id = u.user_id
    """)

    print("\n  [Query 2] Row counts:")
    print(con.execute("""
        SELECT 'raw.orders'         AS tbl, COUNT(*) AS rows FROM raw.orders
        UNION ALL
        SELECT 'staging.stg_orders',        COUNT(*) FROM staging.stg_orders
        UNION ALL
        SELECT 'marts.fct_orders',          COUNT(*) FROM marts.fct_orders
    """).df().to_string(index=False))

    print("\n  [Query 4] Top cities by revenue:")
    print(con.execute("""
        SELECT city,
               ROUND(SUM(amount), 2) AS revenue,
               COUNT(*)              AS orders
        FROM marts.fct_orders
        GROUP BY city ORDER BY revenue DESC LIMIT 5
    """).df().to_string(index=False))

    print("\n  [Query 5] AOV by channel:")
    print(con.execute("""
        SELECT channel,
               ROUND(AVG(amount), 2) AS avg_order_value,
               COUNT(*)              AS orders
        FROM marts.fct_orders
        WHERE channel IS NOT NULL
        GROUP BY channel ORDER BY avg_order_value DESC
    """).df().to_string(index=False))

    print("\n  [Stream CDC] Total loaded:")
    print(con.execute("""
        SELECT COUNT(*)              AS total_rows,
               MIN(order_date)       AS min_date,
               MAX(order_date)       AS max_date,
               ROUND(SUM(amount), 2) AS total_revenue
        FROM raw.orders
    """).df().to_string(index=False))

    con.close()
    print("  OK simulation complete")


def main():
    print("=" * 60)
    print("  Days 74-75: Snowflake Data Loading")
    print("=" * 60)

    print("\n[1/4] Generating SQL scripts...")
    write_utf8(SNOWFLAKE_DIR / "06_stage_copy_into.sql",  STAGE_SQL)
    write_utf8(SNOWFLAKE_DIR / "07_streams_cdc.sql",      STREAMS_SQL)
    write_utf8(SNOWFLAKE_DIR / "snowsql_config.txt",      SNOWSQL_CONFIG)
    write_utf8(SNOWFLAKE_DIR / "profiles_snowflake.yml",  DBT_PROFILE_SNOWFLAKE)

    print("\n[2/4] Generating CSV data...")
    generate_csv_data()

    print("\n[3/4] Simulating COPY INTO via DuckDB...")
    simulate_copy_into()

    print("\n[4/4] Checkpoint...")
    print("""
  [OK] SQL scripts 06-07 (stage, copy into, streams)
  [OK] CSV: orders.csv (1000), users.csv (200)
  [OK] DuckDB: raw -> staging -> marts pipeline
  [OK] SnowSQL config template
    """)

    print("=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print("""
Snowflake steps:
  1. Register: https://signup.snowflake.com
  2. Run scripts 01-05 in Worksheet
  3. Configure snowsql_config.txt
  4. PUT data/orders.csv @raw.orders_stage
  5. Run 06_stage_copy_into.sql
  6. Run 07_streams_cdc.sql

Git:
  git add snowflake_setup/ lesson71_73.py lesson74_75.py
  git commit -m "feat: Days 71-75 Snowflake Architecture + Data Loading"
  git push origin main
""")


if __name__ == "__main__":
    main()