-- snowflake_setup/23_dynamic_tables_mesh.sql
-- Days 105-107: Dynamic Tables + dbt Mesh на уровне аккаунта Snowflake
-- Не выполнялся: Snowflake-аккаунта нет. Запускать по блокам.

-- ══ 1. MESH = ГРАНИЦА ВЛАДЕНИЯ, НЕ ПАПКИ ═════════════════════
--
-- В dbt_mesh/ оба проекта пишут в один файл DuckDB. В Snowflake
-- у каждого проекта своя база и своя роль: platform публикует GOLD,
-- finance читает его и пишет только в свою базу.
--
--   проект     база         роль-писатель   читает
--   ────────   ──────────   ─────────────   ────────────────────
--   platform   PLATFORM     PLATFORM_DBT    BRONZE
--   finance    FINANCE      FINANCE_DBT     PLATFORM.GOLD (public)
--
-- access: public в dbt — обещание. Грант SELECT на PLATFORM.GOLD —
-- то, что реально пускает. Silver (private) finance'у не грантится:
-- без гранта ref() не спасёт, даже если кто-то обойдёт dbt-loom.

USE ROLE SECURITYADMIN;
CREATE ROLE IF NOT EXISTS PLATFORM_DBT;
CREATE ROLE IF NOT EXISTS FINANCE_DBT;

USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS PLATFORM;
CREATE SCHEMA  IF NOT EXISTS PLATFORM.SILVER;
CREATE SCHEMA  IF NOT EXISTS PLATFORM.GOLD;
CREATE DATABASE IF NOT EXISTS FINANCE;
CREATE SCHEMA  IF NOT EXISTS FINANCE.MARTS;

GRANT OWNERSHIP ON SCHEMA PLATFORM.SILVER TO ROLE PLATFORM_DBT COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA PLATFORM.GOLD   TO ROLE PLATFORM_DBT COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA FINANCE.MARTS   TO ROLE FINANCE_DBT  COPY CURRENT GRANTS;

-- finance видит только публичный слой platform
GRANT USAGE  ON DATABASE PLATFORM               TO ROLE FINANCE_DBT;
GRANT USAGE  ON SCHEMA   PLATFORM.GOLD          TO ROLE FINANCE_DBT;
GRANT SELECT ON ALL    TABLES IN SCHEMA PLATFORM.GOLD TO ROLE FINANCE_DBT;
GRANT SELECT ON FUTURE TABLES IN SCHEMA PLATFORM.GOLD TO ROLE FINANCE_DBT;

-- Проверка: у finance нет доступа к Silver
SHOW GRANTS TO ROLE FINANCE_DBT;
-- ожидается: USAGE на PLATFORM и PLATFORM.GOLD, SELECT на таблицы GOLD,
-- ни одной строки про PLATFORM.SILVER

-- Версии модели в Snowflake — это две таблицы рядом:
--   PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V1, PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V2
-- Удобно держать view без суффикса на latest_version, чтобы BI не
-- переписывать при каждом релизе (в dbt — post-hook или macro):
CREATE OR REPLACE VIEW PLATFORM.GOLD.FCT_SUBSCRIPTIONS
    AS SELECT * FROM PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V1;

-- ══ 2. DYNAMIC TABLES ═══════════════════════════════════════
--
-- Dynamic Table — декларация «результат + допустимое отставание».
-- Когда и как обновлять (incremental или full), решает Snowflake.
--
--                       dbt incremental      Dynamic Table
--   кто запускает       оркестратор (cron)   Snowflake по target_lag
--   логика дельты       is_incremental()     выводит сам из запроса
--   свежесть            расписание           target_lag, напр. 1 минута
--   цена                warehouse на прогон  warehouse на каждый refresh
--   цепочки             DAG в dbt/Dagster    DOWNSTREAM lag по графу DT
--   тесты dbt           до публикации        после: DT уже обновилась

USE ROLE FINANCE_DBT;
USE WAREHOUSE TRANSFORM_WH;

CREATE OR REPLACE DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE
    TARGET_LAG   = '15 minutes'
    WAREHOUSE    = TRANSFORM_WH
    REFRESH_MODE = INCREMENTAL
AS
SELECT DATE_TRUNC('month', start_date) AS month,
       plan,
       COUNT(*)  AS new_subs,
       SUM(mrr)  AS new_mrr
FROM PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V2
GROUP BY 1, 2;

-- Почему REFRESH_MODE задан явно: при AUTO Snowflake молча выбирает
-- FULL, если запрос не поддерживает инкремент (некоторые оконные
-- функции, недетерминированные выражения). Явный INCREMENTAL упадёт
-- на создании — лучше узнать сразу, чем по счёту за warehouse.
SHOW DYNAMIC TABLES LIKE 'MART_MRR_LIVE' IN SCHEMA FINANCE.MARTS;
-- колонки: target_lag, refresh_mode, refresh_mode_reason, scheduling_state

-- Промежуточная DT: TARGET_LAG = DOWNSTREAM — обновляется, только
-- когда её требует нижняя DT. Своего расписания нет.
CREATE OR REPLACE DYNAMIC TABLE FINANCE.MARTS.SUBS_ACTIVE
    TARGET_LAG = DOWNSTREAM
    WAREHOUSE  = TRANSFORM_WH
AS
SELECT * FROM PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V2 WHERE end_date IS NULL;

-- История обновлений: сколько строк, сколько длилось, каким способом
SELECT name, state, refresh_action, refresh_trigger,
       statistics:numInsertedRows::INT AS inserted,
       statistics:numDeletedRows::INT  AS deleted,
       DATEDIFF('second', refresh_start_time, refresh_end_time) AS secs
FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY(
    NAME_PREFIX => 'FINANCE.MARTS.'))
ORDER BY refresh_start_time DESC
LIMIT 20;

-- Фактическое отставание против обещанного
SELECT name, target_lag_sec, mean_lag_sec, maximum_lag_sec, time_within_target_lag_ratio
FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_GRAPH_HISTORY())
WHERE qualified_name ILIKE 'FINANCE.MARTS.%';

-- Остановить обновления (например, на время backfill в platform)
ALTER DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE SUSPEND;
ALTER DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE RESUME;
-- Ручной refresh вне расписания
ALTER DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE REFRESH;

-- В dbt это та же модель: dbt_mesh/finance/models/mart_mrr_live.sql,
-- materialized='dynamic_table', target_lag, snowflake_warehouse.
-- dbt создаёт DT и дальше её не гоняет — dbt run только меняет
-- определение, если SQL поменялся.

-- ══ 3. ОЧИСТКА ══════════════════════════════════════════════
-- DROP DYNAMIC TABLE IF EXISTS FINANCE.MARTS.MART_MRR_LIVE;
-- DROP DYNAMIC TABLE IF EXISTS FINANCE.MARTS.SUBS_ACTIVE;
