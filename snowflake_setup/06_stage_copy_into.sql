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
