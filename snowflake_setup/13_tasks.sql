-- snowflake_setup/13_tasks.sql
-- Days 94-96: Tasks — планировщик внутри Snowflake
-- Запуск: Snowflake Worksheet или SnowSQL

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- Task требует отдельной привилегии на уровне аккаунта:
-- GRANT EXECUTE TASK ON ACCOUNT TO ROLE SYSADMIN;

-- ─── 1. Root task: расписание + условие ───────────────────
-- SCHEDULE задаётся ЛИБО интервалом, ЛИБО cron. Не обоими сразу.
CREATE OR REPLACE TASK t_load_stg
    WAREHOUSE = analytics_wh
    SCHEDULE  = 'USING CRON 0 * * * * UTC'   -- каждый час
    -- альтернатива: SCHEDULE = '60 MINUTE'
WHEN
    SYSTEM$STREAM_HAS_DATA('orders_stream_stg')
AS
    INSERT INTO staging.stg_orders (order_id, user_id, amount, city, order_date)
    SELECT order_id, user_id, amount, city, updated_at::DATE
    FROM orders_stream_stg
    WHERE METADATA$ACTION = 'INSERT'
      AND status = 'completed';

-- WHEN — не косметика, а деньги: если условие ложно, задача
-- переходит в SKIPPED и warehouse не просыпается. Проверка
-- SYSTEM$STREAM_HAS_DATA бесплатна, запуск warehouse — нет.

-- ─── 2. Serverless task: без своего warehouse ─────────────
-- Убрать WAREHOUSE → Snowflake сам подбирает compute и биллит
-- посекундно. Дешевле для коротких частых задач: нет 60-секундного
-- минимума и времени прогрева. Дороже для тяжёлых.
CREATE OR REPLACE TASK t_load_stg_serverless
    USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
    SCHEDULE = '5 MINUTE'
AS
    CALL some_procedure();

-- ─── 3. Граф задач: AFTER ─────────────────────────────────
-- Расписание есть ТОЛЬКО у корня. У детей — зависимость.
CREATE OR REPLACE TASK t_build_marts
    WAREHOUSE = analytics_wh
    AFTER t_load_stg
AS
    INSERT INTO marts.daily_revenue (order_date, revenue)
    SELECT order_date, SUM(amount)
    FROM staging.stg_orders
    GROUP BY 1;

CREATE OR REPLACE TASK t_audit_log
    WAREHOUSE = analytics_wh
    AFTER t_load_stg
AS
    INSERT INTO ops.pipeline_audit (run_ts, rows_loaded)
    SELECT CURRENT_TIMESTAMP(), COUNT(*) FROM staging.stg_orders;

-- Задача с несколькими AFTER стартует, когда завершились ВСЕ родители.
CREATE OR REPLACE TASK t_notify
    WAREHOUSE = analytics_wh
    AFTER t_build_marts, t_audit_log
AS
    CALL ops.send_slack_alert('pipeline ok');

-- ─── 4. Запуск и остановка ────────────────────────────────
-- Созданная задача СОЗДАЁТСЯ ПРИОСТАНОВЛЕННОЙ. Забыть RESUME —
-- самая частая причина «таск не работает».
-- Порядок обязателен: сначала дети, потом корень.
ALTER TASK t_notify      RESUME;
ALTER TASK t_build_marts RESUME;
ALTER TASK t_audit_log   RESUME;
ALTER TASK t_load_stg    RESUME;   -- корень последним

-- Правка ребёнка требует остановки КОРНЯ, а не самого ребёнка.
ALTER TASK t_load_stg SUSPEND;

-- Ручной прогон всего графа, не дожидаясь расписания:
EXECUTE TASK t_load_stg;

-- ─── 5. Пересечение запусков ──────────────────────────────
-- По умолчанию ALLOW_OVERLAPPING_EXECUTION = FALSE: если предыдущий
-- прогон графа ещё идёт, очередной запуск по расписанию
-- ПРОПУСКАЕТСЯ молча. Задача, которая дольше своего интервала,
-- тихо теряет запуски — ловится только в task_history.
ALTER TASK t_load_stg SET ALLOW_OVERLAPPING_EXECUTION = FALSE;

-- Защита от вечно висящей задачи:
ALTER TASK t_load_stg SET USER_TASK_TIMEOUT_MS = 3600000;   -- 1 час

-- ─── 6. Finalizer: что выполнить после графа в любом случае ─
CREATE OR REPLACE TASK t_cleanup
    WAREHOUSE = analytics_wh
    FINALIZE = t_load_stg
AS
    CALL ops.release_locks();

-- ─── 7. Наблюдаемость ─────────────────────────────────────
SELECT name, state, scheduled_time, completed_time, error_message,
       DATEDIFF('second', scheduled_time, completed_time) AS duration_s
FROM TABLE(information_schema.task_history(
        SCHEDULED_TIME_RANGE_START => DATEADD('day', -1, CURRENT_TIMESTAMP())))
ORDER BY scheduled_time DESC;

-- state: SUCCEEDED | FAILED | SKIPPED | CANCELLED
-- SKIPPED — это WHEN вернул FALSE или пересечение запусков.
-- Отличать SKIPPED от FAILED обязательно: первое штатно, второе нет.

SELECT SYSTEM$TASK_DEPENDENTS_ENABLE('t_load_stg');

-- Алерты о падениях — через notification integration:
ALTER TASK t_load_stg SET ERROR_INTEGRATION = my_email_int;
