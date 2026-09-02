-- snowflake_setup/10_zero_copy_clone.sql
-- Days 91-93: Zero Copy Clone — копия без копирования данных

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

-- ─── 1. Клон таблицы ──────────────────────────────────────
-- Копируются метаданные: список указателей на micro-partitions.
-- Байты данных не дублируются. Время не зависит от размера таблицы.
CREATE TABLE raw.orders_backup CLONE raw.orders;

-- ─── 2. Клон схемы и базы ─────────────────────────────────
-- Так делается dev-окружение с полными prod-данными за секунды.
CREATE SCHEMA raw_dev CLONE raw;
CREATE DATABASE analytics_dev CLONE analytics_db;

-- ─── 3. Клон + Time Travel вместе ─────────────────────────
-- Самая полезная комбинация: воспроизвести баг на вчерашних данных,
-- не трогая prod.
CREATE TABLE raw.orders_yesterday CLONE raw.orders AT (OFFSET => -60 * 60 * 24);

CREATE DATABASE analytics_debug CLONE analytics_db
    BEFORE (STATEMENT => '<query_id сбойной загрузки>');

-- ─── 4. Copy-on-write: расходятся только изменённые партиции ──
UPDATE raw.orders_backup SET status = 'test' WHERE order_id < 100;

-- Оригинал не тронут:
SELECT status, COUNT(*) FROM raw.orders        GROUP BY 1;
SELECT status, COUNT(*) FROM raw.orders_backup GROUP BY 1;

-- Расход хранения появился только на изменённых micro-partitions.
-- clone_group_id связывает клоны, выросшие из одной таблицы.
SELECT
    table_name,
    clone_group_id,
    active_bytes / POW(1024, 2) AS active_mb
FROM snowflake.account_usage.table_storage_metrics
WHERE table_name IN ('ORDERS', 'ORDERS_BACKUP')
  AND deleted = FALSE;

-- ─── 5. Что клон НЕ наследует ─────────────────────────────
-- 5.1 GRANTS на таблице — по умолчанию нет. Нужен COPY GRANTS.
CREATE TABLE raw.orders_backup2 CLONE raw.orders COPY GRANTS;

-- 5.2 Внешние stage: клонируется определение, файлы в S3/GCS не копируются.
-- 5.3 Внутренние named stage не клонируются вовсе.
-- 5.4 У Snowpipe в клоне обнуляется история загруженных файлов.
-- 5.5 TEMPORARY и TRANSIENT таблицы нельзя клонировать в PERMANENT.

-- ─── 6. Уборка ────────────────────────────────────────────
-- Клоны выглядят бесплатными ровно до первой записи в них.
-- Забытый клон prod-базы месячной давности — это счёт за хранение.
DROP DATABASE IF EXISTS analytics_dev;
DROP DATABASE IF EXISTS analytics_debug;
