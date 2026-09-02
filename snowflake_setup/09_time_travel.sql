-- snowflake_setup/09_time_travel.sql
-- Days 91-93: Time Travel — чтение прошлого состояния таблицы
-- Запуск: Snowflake Worksheet или SnowSQL

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- ─── 1. Сколько истории вообще доступно ───────────────────
-- Standard edition: 0 или 1 день. Enterprise: до 90 дней.
-- Ретенция настраивается на таблице, схеме или базе — наследуется вниз.
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS' IN TABLE orders;

ALTER TABLE orders SET DATA_RETENTION_TIME_IN_DAYS = 7;

-- ─── 2. Три способа указать точку во времени ──────────────

-- 2.1 AT TIMESTAMP — абсолютный момент
SELECT COUNT(*) AS rows_at_ts
FROM orders AT (TIMESTAMP => '2026-08-22 10:00:00'::TIMESTAMP_LTZ);

-- 2.2 AT OFFSET — относительный сдвиг в секундах, всегда отрицательный
SELECT COUNT(*) AS rows_15_min_ago
FROM orders AT (OFFSET => -60 * 15);

-- 2.3 BEFORE STATEMENT — состояние ДО конкретного запроса.
-- Самый точный вариант при инциденте: не надо угадывать секунды.
SELECT query_id, start_time, LEFT(query_text, 80) AS query_text
FROM TABLE(information_schema.query_history_by_session())
WHERE query_text ILIKE 'DELETE FROM ORDERS%'
ORDER BY start_time DESC
LIMIT 5;

SELECT COUNT(*) FROM orders BEFORE (STATEMENT => '<подставь query_id из запроса выше>');

-- ─── 3. Сценарий инцидента: случайный DELETE ──────────────

SELECT COUNT(*) AS before_delete FROM orders;

DELETE FROM orders WHERE amount < 50;          -- забыли вторую половину WHERE

SELECT COUNT(*) AS after_delete FROM orders;
SELECT COUNT(*) AS was_a_minute_ago FROM orders AT (OFFSET => -60);

-- 3.1 Точечное восстановление: вернуть только потерянные строки.
-- MINUS в Snowflake — синоним EXCEPT.
INSERT INTO orders
SELECT * FROM orders AT (OFFSET => -60)
MINUS
SELECT * FROM orders;

-- 3.2 Полная замена таблицы состоянием до сбойного запроса.
-- Обрывает Time Travel самой таблицы: у CREATE OR REPLACE история новая.
CREATE OR REPLACE TABLE orders AS
SELECT * FROM orders BEFORE (STATEMENT => '<query_id>');

-- ─── 4. UNDROP — восстановление удалённой таблицы ─────────
-- Работает в пределах окна ретенции. Схемы и базы тоже.

DROP TABLE orders;
SHOW TABLES HISTORY LIKE 'ORDERS';             -- колонка dropped_on
UNDROP TABLE orders;

-- Если после DROP уже создали новую таблицу с тем же именем,
-- UNDROP упадёт с конфликтом имён: сначала переименуй новую.
ALTER TABLE orders RENAME TO orders_new;
UNDROP TABLE orders;

-- ─── 5. Сколько это стоит ─────────────────────────────────
-- Time Travel — это хранение старых micro-partitions. Оно оплачивается.
SELECT
    table_schema,
    table_name,
    active_bytes / POW(1024, 3)      AS active_gb,
    time_travel_bytes / POW(1024, 3) AS time_travel_gb,
    failsafe_bytes / POW(1024, 3)    AS failsafe_gb
FROM snowflake.account_usage.table_storage_metrics
WHERE deleted = FALSE
ORDER BY time_travel_bytes DESC
LIMIT 20;
