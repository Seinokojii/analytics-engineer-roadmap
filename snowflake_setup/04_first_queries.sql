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
