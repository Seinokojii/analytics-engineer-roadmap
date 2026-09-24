-- snowflake_setup/22_medallion_layers.sql
-- Days 101-104: Medallion Architecture на Snowflake
-- Запускать в Worksheet по блокам, роль ACCOUNTADMIN (блок 1) и SECURITYADMIN (блок 3).

-- ══ ЗАЧЕМ СЛОИ — ЭТО СХЕМЫ, А НЕ ПАПКИ ═════════════════════
--
-- Папки в dbt видит только разработчик. Схемы видит Snowflake:
-- на них вешаются гранты, retention и тип таблиц. Поэтому граница
-- слоя — это граница схемы, и у каждого слоя своя цена и свой доступ.
--
--   слой     кто пишет     кто читает           тип схемы   Time Travel
--   ──────   ───────────   ──────────────────   ─────────   ───────────
--   BRONZE   LOADER        TRANSFORMER          permanent   долгий: это
--            (Airbyte)                                      единственная копия
--   SILVER   TRANSFORMER   TRANSFORMER          TRANSIENT   0-1 день: всё
--            (dbt)                                          пересобирается
--   GOLD     TRANSFORMER   REPORTER (BI, API)   permanent   1+ день: откат
--            (dbt)                                          витрины после
--                                                           плохого деплоя

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE COMPUTE_WH;

-- ── 1. Схемы ────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS ANALYTICS;
USE DATABASE ANALYTICS;

-- Bronze: сюда пишет Airbyte (destination namespace = BRONZE).
-- Fail-safe и длинный Time Travel нужны именно здесь: из источника
-- историю не восстановить, а snapshot'ы dbt тоже лежат тут.
CREATE SCHEMA IF NOT EXISTS BRONZE
    DATA_RETENTION_TIME_IN_DAYS = 30;     -- 30 требует Enterprise; на Standard максимум 1

-- Silver: TRANSIENT. Нет Fail-safe (7 дней хранения, за которые
-- платишь), потому что любой объект здесь пересобирается из Bronze
-- одной командой dbt build. Платить за страховку восстановимого — лишнее.
CREATE TRANSIENT SCHEMA IF NOT EXISTS SILVER
    DATA_RETENTION_TIME_IN_DAYS = 1;

-- Gold: permanent. Пересобрать тоже можно, но на это нужно время,
-- а дашборды и API читают его прямо сейчас. Time Travel нужен для
-- быстрого отката: SELECT ... AT(OFFSET => -3600) вместо пересборки.
CREATE SCHEMA IF NOT EXISTS GOLD
    DATA_RETENTION_TIME_IN_DAYS = 7;

-- Таблица в TRANSIENT-схеме наследует TRANSIENT автоматически.
-- Проверка: колонка "options" = TRANSIENT, retention_time = 1.
SHOW SCHEMAS IN DATABASE ANALYTICS;

-- ── 2. Как dbt попадает в эти схемы ─────────────────────────
-- dbt_project.yml:   staging: +schema: silver   marts: +schema: gold
-- macros/generate_schema_name.sql на target prod отдаёт custom-схему
-- как есть -> SILVER / GOLD. На dev / ci -> <target.schema>_silver,
-- чтобы разработчик не писал в общий GOLD.
-- Проверка после dbt build --target prod:
SELECT table_schema, table_type, is_transient, count(*) AS objects
FROM ANALYTICS.INFORMATION_SCHEMA.TABLES
WHERE table_schema IN ('BRONZE', 'SILVER', 'GOLD')
GROUP BY 1, 2, 3
ORDER BY 1, 2;

-- ── 3. RBAC по слоям ────────────────────────────────────────
USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS LOADER;        -- Airbyte
CREATE ROLE IF NOT EXISTS TRANSFORMER;   -- dbt
CREATE ROLE IF NOT EXISTS REPORTER;      -- Lightdash, metrics_api

GRANT USAGE ON DATABASE ANALYTICS TO ROLE LOADER;
GRANT USAGE ON DATABASE ANALYTICS TO ROLE TRANSFORMER;
GRANT USAGE ON DATABASE ANALYTICS TO ROLE REPORTER;

-- LOADER: пишет только в Bronze и больше ничего не видит
GRANT USAGE, CREATE TABLE ON SCHEMA ANALYTICS.BRONZE TO ROLE LOADER;

-- TRANSFORMER: читает Bronze, владеет Silver и Gold
GRANT USAGE ON SCHEMA ANALYTICS.BRONZE TO ROLE TRANSFORMER;
GRANT SELECT ON ALL TABLES    IN SCHEMA ANALYTICS.BRONZE TO ROLE TRANSFORMER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS.BRONZE TO ROLE TRANSFORMER;
GRANT ALL ON SCHEMA ANALYTICS.SILVER TO ROLE TRANSFORMER;
GRANT ALL ON SCHEMA ANALYTICS.GOLD   TO ROLE TRANSFORMER;

-- REPORTER: только Gold. Здесь и видна польза слоёв как схем:
-- один FUTURE GRANT на схему, и любая новая витрина доступна BI
-- сразу после dbt build. Сырые таблицы с email и телефонами
-- в Bronze для BI недоступны физически, а не по договорённости.
GRANT USAGE ON SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON ALL TABLES    IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON ALL VIEWS     IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;

-- Ловушка: вьюха в GOLD, которая читает BRONZE. Обычная вьюха
-- выполняется с правами владельца (TRANSFORMER), и REPORTER через неё
-- увидит Bronze. Контракт «Gold не читает Bronze» в dbt (step 2 урока)
-- закрывает именно эту дыру, а не только эстетику графа.

-- ── 4. Проверка изоляции ────────────────────────────────────
USE ROLE REPORTER;
SELECT count(*) FROM ANALYTICS.GOLD.FCT_ORDERS;          -- ок
SELECT count(*) FROM ANALYTICS.BRONZE.RAW_ORDERS;        -- ожидаем: insufficient privileges
SELECT count(*) FROM ANALYTICS.SILVER.STG_ORDERS;        -- ожидаем: insufficient privileges

-- ── 5. Миграция существующего проекта ───────────────────────
-- dbt не удаляет объект, когда модель меняет схему. После переезда
-- в старой схеме остаются таблицы-сироты, которые выглядят живыми.
-- Найти их: объекты старой схемы, которые не обновлялись после деплоя.
USE ROLE TRANSFORMER;
SELECT table_schema, table_name, last_altered
FROM ANALYTICS.INFORMATION_SCHEMA.TABLES
WHERE table_schema = 'PUBLIC'
  AND last_altered < DATEADD('day', -2, CURRENT_TIMESTAMP())
ORDER BY last_altered;
-- Удалять — только после того, как exposures и ACCESS_HISTORY
-- показали, что их никто не читает:
SELECT direct_objects_accessed, user_name, query_start_time
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
WHERE query_start_time > DATEADD('day', -14, CURRENT_TIMESTAMP())
  AND ARRAY_TO_STRING(direct_objects_accessed, ',') ILIKE '%PUBLIC.FCT_ORDERS%'
LIMIT 50;
