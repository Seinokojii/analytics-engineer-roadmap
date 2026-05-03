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
