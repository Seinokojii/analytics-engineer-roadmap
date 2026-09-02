-- snowflake_setup/14_snowpipe.sql
-- Days 94-96: Snowpipe — continuous загрузка по событию
-- Запуск: Snowflake Worksheet или SnowSQL
-- Продолжает 06_stage_copy_into.sql из дней 74-75.

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- ─── 1. Чем PIPE отличается от COPY INTO ──────────────────
-- COPY INTO   — ты решаешь, когда грузить. Нужен warehouse.
-- Snowpipe    — грузит сам, когда файл появился в стейдже.
--               Своего warehouse нет: serverless, биллинг за
--               обработанные файлы, отдельной строкой в счёте.
-- Задержка Snowpipe — минуты, не секунды. Это не стриминг.
-- Нужны секунды → Snowpipe Streaming API, другой продукт.

CREATE OR REPLACE STAGE orders_stage
    URL = 's3://my-bucket/orders/'
    STORAGE_INTEGRATION = s3_int
    FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1);

-- ─── 2. Сам pipe ──────────────────────────────────────────
CREATE OR REPLACE PIPE orders_pipe
    AUTO_INGEST = TRUE
AS
    COPY INTO raw.orders (order_id, user_id, amount, city, status, updated_at)
    FROM @orders_stage
    FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1)
    ON_ERROR = CONTINUE;

-- AUTO_INGEST = TRUE требует уведомлений от облака.
-- notification_channel из вывода ниже — ARN очереди SQS,
-- который прописывается в S3 Event Notification на стороне AWS.
SHOW PIPES LIKE 'orders_pipe';

-- ─── 3. Дедупликация файлов ───────────────────────────────
-- Pipe помнит загруженные файлы 14 дней и повторно их не берёт.
-- Отсюда два следствия:
--   * перезалить тот же файл в течение 14 дней — он будет
--     проигнорирован. Нужен REFRESH или новое имя.
--   * файл старше 14 дней при повторной заливке загрузится снова
--     и задвоит данные.
ALTER PIPE orders_pipe REFRESH;
ALTER PIPE orders_pipe REFRESH PREFIX = '2026/09/' MODIFIED_AFTER = '2026-09-01';

-- ─── 4. Наблюдаемость ─────────────────────────────────────
SELECT SYSTEM$PIPE_STATUS('orders_pipe');
-- executionState: RUNNING | STOPPED_*  ·  pendingFileCount  ·  lastReceivedMessageTimestamp
-- pendingFileCount растёт и не падает → уведомления идут, а загрузка встала.
-- lastReceivedMessageTimestamp старый → уведомления вообще не доходят,
-- проблема на стороне S3/SQS, а не Snowflake.

SELECT file_name, status, row_count, row_parsed, first_error_message,
       last_load_time
FROM TABLE(information_schema.copy_history(
        TABLE_NAME => 'raw.orders',
        START_TIME => DATEADD('hour', -24, CURRENT_TIMESTAMP())))
ORDER BY last_load_time DESC;

ALTER PIPE orders_pipe SET PIPE_EXECUTION_PAUSED = TRUE;

-- ─── 5. Полная event-driven цепочка ───────────────────────
-- S3 файл → SQS → PIPE → raw.orders → STREAM → TASK → staging → marts
-- Ни одного внешнего оркестратора. Вся цепочка живёт в Snowflake.
-- Плата за это — наблюдаемость размазана по трём разным местам:
-- copy_history, SHOW STREAMS, task_history.

-- ─── 6. Экономика ─────────────────────────────────────────
-- Snowpipe берёт накладные расходы за КАЖДЫЙ файл. Тысяча файлов
-- по 1 КБ обойдётся дороже одного файла на 1 МБ при том же объёме.
-- Рекомендация Snowflake: файлы 100-250 МБ сжатыми.
SELECT pipe_name, SUM(credits_used) AS credits, SUM(files_inserted) AS files
FROM snowflake.account_usage.pipe_usage_history
WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1;
