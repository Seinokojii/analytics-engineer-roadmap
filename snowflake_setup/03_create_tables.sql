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
