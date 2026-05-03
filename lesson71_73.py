#!/usr/bin/env python3
"""
lesson71_73.py - Days 71-73: Snowflake Architecture
Zapusk: python lesson71_73.py

Chto delaet:
  1. Generiruet vse SQL skripty dlya Snowflake setup
  2. Sozdaet strukturu papok dlya Snowflake proekta
  3. Delaet lokalnuyu simulyatsiyu v DuckDB (esli Snowflake net)

Snowflake Trial: https://signup.snowflake.com
"""

import duckdb
from pathlib import Path
from datetime import date

PROJECT_ROOT   = Path(__file__).parent
SNOWFLAKE_DIR  = PROJECT_ROOT / "snowflake_setup"
SNOWFLAKE_DIR.mkdir(exist_ok=True)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


# ── SQL 1: Database + Schema setup ───────────────────────

SETUP_SQL = """\
-- snowflake_setup/01_setup_database.sql
-- Day 71: Sozdanie osnovnoy struktury v Snowflake
-- Zapusk: v Snowflake Worksheet ili SnowSQL

-- 1. Ispolzuy ACCOUNTADMIN dlya nachalnoy nastroyki
USE ROLE ACCOUNTADMIN;

-- 2. Virtualnyy sklad (compute)
CREATE WAREHOUSE IF NOT EXISTS analytics_wh
    WAREHOUSE_SIZE    = 'XSMALL'
    AUTO_SUSPEND      = 60          -- vyklyuchaetsya cherez 60 sek prostoyi
    AUTO_RESUME       = TRUE        -- vklyuchaetsya avtomaticheski pri zaprose
    INITIALLY_SUSPENDED = TRUE;     -- starta vyklyuchennym (ekonomiya)

-- 3. Baza dannykh
CREATE DATABASE IF NOT EXISTS analytics_db;

-- 4. Skhemy (bronza / serebrо / zoloto)
CREATE SCHEMA IF NOT EXISTS analytics_db.raw;      -- Bronze: syrye dannye
CREATE SCHEMA IF NOT EXISTS analytics_db.staging;  -- Silver: ochistka
CREATE SCHEMA IF NOT EXISTS analytics_db.marts;    -- Gold: biznes-modeli

-- 5. Podklyuchaem sklad
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
"""

# ── SQL 2: RBAC Roles ─────────────────────────────────────

RBAC_SQL = """\
-- snowflake_setup/02_roles_rbac.sql
-- Day 71: Roles i RBAC
-- Ierarkhiya: ACCOUNTADMIN -> SYSADMIN -> analyst_role -> readonly_role

USE ROLE ACCOUNTADMIN;

-- Sozdaem roli
CREATE ROLE IF NOT EXISTS analyst_role;
CREATE ROLE IF NOT EXISTS readonly_role;

-- Ierarkhiya: analyst_role -> SYSADMIN -> ACCOUNTADMIN
GRANT ROLE analyst_role  TO ROLE SYSADMIN;
GRANT ROLE readonly_role TO ROLE analyst_role;

-- analyst_role: mozhet delat VSE v analytics_db
GRANT USAGE  ON WAREHOUSE analytics_wh          TO ROLE analyst_role;
GRANT USAGE  ON DATABASE analytics_db           TO ROLE analyst_role;
GRANT USAGE  ON ALL SCHEMAS IN DATABASE analytics_db TO ROLE analyst_role;
GRANT CREATE TABLE ON SCHEMA analytics_db.raw       TO ROLE analyst_role;
GRANT CREATE TABLE ON SCHEMA analytics_db.staging   TO ROLE analyst_role;
GRANT CREATE TABLE ON SCHEMA analytics_db.marts     TO ROLE analyst_role;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN DATABASE analytics_db           TO ROLE analyst_role;

-- readonly_role: tolko SELECT
GRANT USAGE  ON WAREHOUSE analytics_wh          TO ROLE readonly_role;
GRANT USAGE  ON DATABASE analytics_db           TO ROLE readonly_role;
GRANT USAGE  ON ALL SCHEMAS IN DATABASE analytics_db TO ROLE readonly_role;
GRANT SELECT ON ALL TABLES IN DATABASE analytics_db  TO ROLE readonly_role;

-- Future grants (dlya novykh tablic)
GRANT SELECT ON FUTURE TABLES IN DATABASE analytics_db TO ROLE readonly_role;
GRANT SELECT ON FUTURE TABLES IN DATABASE analytics_db TO ROLE analyst_role;

-- Naznachaem rol polzovatelyu (zameni YOUR_USERNAME)
-- GRANT ROLE analyst_role TO USER YOUR_USERNAME;

-- Proverka
SHOW ROLES;
SHOW GRANTS TO ROLE analyst_role;
"""

# ── SQL 3: DDL таблицы ────────────────────────────────────

DDL_SQL = """\
-- snowflake_setup/03_create_tables.sql
-- Day 71: DDL - sozdanie tablic v raw / staging / marts

USE ROLE analyst_role;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

-- ── RAW (Bronze) ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS raw.orders (
    order_id    NUMBER       NOT NULL,
    user_id     NUMBER       NOT NULL,
    amount      FLOAT        NOT NULL,
    status      VARCHAR(20)  NOT NULL,
    city        VARCHAR(50),
    order_date  DATE         NOT NULL,
    loaded_at   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS raw.users (
    user_id     NUMBER       NOT NULL,
    email       VARCHAR(200),
    city        VARCHAR(50),
    channel     VARCHAR(50),
    created_at  DATE
);

-- ── STAGING (Silver) ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS staging.stg_orders (
    order_id    NUMBER,
    user_id     NUMBER,
    amount      FLOAT,
    city        VARCHAR(50),
    order_date  DATE
);

CREATE TABLE IF NOT EXISTS staging.stg_users (
    user_id    NUMBER,
    email      VARCHAR(200),
    city       VARCHAR(50),
    channel    VARCHAR(50),
    created_at DATE
);

-- ── MARTS (Gold) ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS marts.fct_orders (
    order_id    NUMBER,
    user_id     NUMBER,
    email       VARCHAR(200),
    city        VARCHAR(50),
    channel     VARCHAR(50),
    amount      FLOAT,
    order_date  DATE
);

CREATE TABLE IF NOT EXISTS marts.dim_customers (
    user_id         NUMBER,
    email           VARCHAR(200),
    city            VARCHAR(50),
    channel         VARCHAR(50),
    total_orders    NUMBER,
    total_spent     FLOAT,
    last_order_date DATE
);
"""

# ── SQL 4: Первые 10 запросов ─────────────────────────────

QUERIES_SQL = """\
-- snowflake_setup/04_first_queries.sql
-- Day 71: 10 osnovnykh SQL zaprosov k Snowflake
-- Analogichny nashim DuckDB zaprosam

USE ROLE analyst_role;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

-- 1. Proverit strukturu bazy
SHOW SCHEMAS IN DATABASE analytics_db;

-- 2. Skolko strok v tablitsakh
SELECT 'raw.orders'       AS tbl, COUNT(*) AS rows FROM raw.orders
UNION ALL
SELECT 'raw.users',              COUNT(*) FROM raw.users
UNION ALL
SELECT 'marts.fct_orders',       COUNT(*) FROM marts.fct_orders;

-- 3. Revenue za poslednie 30 dney
SELECT
    DATE_TRUNC('month', order_date) AS month,
    SUM(amount)                     AS revenue,
    COUNT(*)                        AS orders
FROM marts.fct_orders
WHERE order_date >= DATEADD('day', -30, CURRENT_DATE())
GROUP BY 1
ORDER BY 1 DESC;

-- 4. Top-5 gorodov po revenue
SELECT
    city,
    ROUND(SUM(amount), 2)     AS total_revenue,
    COUNT(DISTINCT order_id)  AS order_count
FROM marts.fct_orders
WHERE city IS NOT NULL
GROUP BY city
ORDER BY total_revenue DESC
LIMIT 5;

-- 5. AOV (Average Order Value) po kanalam
SELECT
    channel,
    ROUND(AVG(amount), 2)     AS avg_order_value,
    COUNT(*)                  AS orders
FROM marts.fct_orders
GROUP BY channel
ORDER BY avg_order_value DESC;

-- 6. Window function: ranking gorodov
SELECT
    city,
    ROUND(SUM(amount), 2)                              AS revenue,
    RANK() OVER (ORDER BY SUM(amount) DESC)            AS rank
FROM marts.fct_orders
GROUP BY city;

-- 7. Rolling 7-day revenue
SELECT
    order_date,
    ROUND(SUM(amount), 2)                              AS daily_revenue,
    ROUND(AVG(SUM(amount)) OVER (
        ORDER BY order_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 2)                                              AS rolling_7d
FROM marts.fct_orders
GROUP BY order_date
ORDER BY order_date;

-- 8. Customer LTV
SELECT
    user_id,
    COUNT(DISTINCT order_id)  AS orders,
    ROUND(SUM(amount), 2)     AS ltv,
    ROUND(AVG(amount), 2)     AS avg_order
FROM marts.fct_orders
GROUP BY user_id
ORDER BY ltv DESC
LIMIT 10;

-- 9. Cohort retention (month 0 vs month 1)
WITH first_order AS (
    SELECT user_id, MIN(order_date) AS first_date
    FROM marts.fct_orders GROUP BY user_id
),
cohorts AS (
    SELECT
        o.user_id,
        DATE_TRUNC('month', f.first_date)   AS cohort_month,
        DATEDIFF('month', f.first_date,
                 o.order_date)               AS month_num
    FROM marts.fct_orders o
    JOIN first_order f ON o.user_id = f.user_id
)
SELECT cohort_month, month_num,
       COUNT(DISTINCT user_id) AS users
FROM cohorts
WHERE month_num <= 3
GROUP BY cohort_month, month_num
ORDER BY cohort_month, month_num;

-- 10. Snowflake-specific: QUERY_HISTORY (metadannye)
SELECT query_text, execution_time, bytes_scanned
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
    DATE_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP())
))
ORDER BY start_time DESC
LIMIT 10;
"""

# ── SQL 5: Micro-partitioning demo ───────────────────────

MICROPARTITION_SQL = """\
-- snowflake_setup/05_micropartitioning.sql
-- Day 71: Micro-partitioning i Clustering Keys
-- Kak Snowflake khranit dannye (analogiya: Parquet row groups)

USE ROLE analyst_role;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

-- Bez klasterizatsii: Snowflake sam vybyraet mikropartitsii
-- Kazhday mikropartitsiya = 16-512 MB szhatkh dannykh

-- Posmotrm statistiku mikropartitsiy
SELECT SYSTEM$CLUSTERING_INFORMATION(
    'marts.fct_orders',
    '(order_date)'
);

-- Tablitsa s Clustering Key (dlya bolshikh tablic, >1TB)
-- Snowflake avtomaticheski pereklasteriziruet v fone
CREATE TABLE IF NOT EXISTS marts.fct_orders_clustered
CLUSTER BY (order_date, city)  -- Clustering key: chastyy filtr
AS SELECT * FROM marts.fct_orders;

-- Proverit effektivnost skanirovanniya
-- (posle zagruzki dannykh)
SELECT
    COUNT(*)                          AS total_rows,
    SYSTEM$CLUSTERING_DEPTH(
        'marts.fct_orders_clustered'
    )                                 AS clustering_depth
FROM marts.fct_orders_clustered;
"""


# ── DuckDB локальная симуляция ────────────────────────────

def run_duckdb_simulation():
    print("\n" + "=" * 55)
    print("  DuckDB Simulation (bez Snowflake)")
    print("=" * 55)

    db_path = SNOWFLAKE_DIR / "snowflake_simulation.duckdb"
    con = duckdb.connect(str(db_path))

    # Имитируем схемы
    for schema in ["raw", "staging", "marts"]:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # Создаём таблицы
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.orders (
            order_id   INTEGER, user_id INTEGER,
            amount     FLOAT,   status  VARCHAR,
            city       VARCHAR, order_date DATE,
            loaded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS raw.users (
            user_id INTEGER, email VARCHAR,
            city VARCHAR, channel VARCHAR, created_at DATE
        )
    """)

    # Вставляем тестовые данные
    con.execute("""
        INSERT INTO raw.orders VALUES
        (1, 1, 1500.0, 'completed', 'MOSCOW',    '2024-01-15', NOW()),
        (2, 2, 2300.0, 'completed', 'SPB',       '2024-01-16', NOW()),
        (3, 1,  800.0, 'pending',   'MOSCOW',    '2024-01-17', NOW()),
        (4, 3, 4500.0, 'completed', 'KAZAN',     '2024-02-01', NOW()),
        (5, 2, 1200.0, 'completed', 'SPB',       '2024-02-05', NOW())
    """)
    con.execute("""
        INSERT INTO raw.users VALUES
        (1, 'user1@example.com', 'MOSCOW', 'organic',  '2023-05-01'),
        (2, 'user2@example.com', 'SPB',    'paid',     '2023-06-15'),
        (3, 'user3@example.com', 'KAZAN',  'referral', '2023-07-20')
    """)

    # Запрос 1: Revenue по городам
    print("\n[Query 4] Revenue by city:")
    result = con.execute("""
        SELECT city,
            ROUND(SUM(amount), 2) AS total_revenue,
            COUNT(*) AS orders
        FROM raw.orders
        WHERE status = 'completed'
        GROUP BY city ORDER BY total_revenue DESC
    """).df()
    print(result.to_string(index=False))

    # Запрос 2: AOV
    print("\n[Query 5] AOV by channel:")
    result = con.execute("""
        SELECT u.channel,
            ROUND(AVG(o.amount), 2) AS avg_order_value,
            COUNT(*) AS orders
        FROM raw.orders o JOIN raw.users u ON o.user_id = u.user_id
        WHERE o.status = 'completed'
        GROUP BY u.channel ORDER BY avg_order_value DESC
    """).df()
    print(result.to_string(index=False))

    # Запрос 3: LTV
    print("\n[Query 8] Customer LTV:")
    result = con.execute("""
        SELECT user_id,
            COUNT(*) AS orders,
            ROUND(SUM(amount), 2) AS ltv
        FROM raw.orders
        WHERE status = 'completed'
        GROUP BY user_id ORDER BY ltv DESC
    """).df()
    print(result.to_string(index=False))

    con.close()
    print(f"\n  OK Simulation DB: {db_path.relative_to(PROJECT_ROOT)}")


def main():
    print("=" * 60)
    print("  Days 71-73: Snowflake Architecture Setup")
    print("=" * 60)

    print("\n[1/3] Creating SQL scripts...")
    write_utf8(SNOWFLAKE_DIR / "01_setup_database.sql",   SETUP_SQL)
    write_utf8(SNOWFLAKE_DIR / "02_roles_rbac.sql",       RBAC_SQL)
    write_utf8(SNOWFLAKE_DIR / "03_create_tables.sql",    DDL_SQL)
    write_utf8(SNOWFLAKE_DIR / "04_first_queries.sql",    QUERIES_SQL)
    write_utf8(SNOWFLAKE_DIR / "05_micropartitioning.sql", MICROPARTITION_SQL)

    print("\n[2/3] Running DuckDB simulation...")
    run_duckdb_simulation()

    print("\n[3/3] Creating README...")
    readme = (
        f"# Snowflake Setup — Days 71-73\n\n"
        f"Generated: {date.today()}\n\n"
        "## Steps\n\n"
        "1. Register: https://signup.snowflake.com\n"
        "2. Run 01_setup_database.sql in Worksheet\n"
        "3. Run 02_roles_rbac.sql\n"
        "4. Run 03_create_tables.sql\n"
        "5. Run 04_first_queries.sql\n\n"
        "## Architecture\n\n"
        "```\n"
        "analytics_db/\n"
        "  raw/      <- Bronze: COPY INTO from Stage\n"
        "  staging/  <- Silver: cleaned data\n"
        "  marts/    <- Gold:   business models\n"
        "```\n\n"
        "## Warehouse config\n\n"
        "- Size: XSMALL (dev), SMALL (prod)\n"
        "- Auto-suspend: 60s (save credits)\n"
        "- Auto-resume: TRUE (transparent to users)\n"
    )
    write_utf8(SNOWFLAKE_DIR / "README.md", readme)

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print(f"""
Snowflake:
  1. Register: https://signup.snowflake.com
  2. Worksheet -> run snowflake_setup/01_setup_database.sql
  3. Worksheet -> run 02_roles_rbac.sql
  4. Worksheet -> run 03_create_tables.sql
  5. Worksheet -> run 04_first_queries.sql

DuckDB simulation: snowflake_setup/snowflake_simulation.duckdb

Git:
  git add snowflake_setup/ lesson71_73.py
  git commit -m "feat: Days 71-73 Snowflake Architecture"
  git push origin main
""")


if __name__ == "__main__":
    main()