-- snowflake_setup/07_streams_cdc.sql
-- Day 74: Streams CDC

USE ROLE analyst_role;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

CREATE STREAM IF NOT EXISTS raw.orders_stream
    ON TABLE raw.orders
    COMMENT = 'CDC stream: izmeneniya v raw.orders';

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
