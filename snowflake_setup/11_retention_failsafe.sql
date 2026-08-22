-- snowflake_setup/11_retention_failsafe.sql
-- Days 91-93: ретенция, Fail-safe и типы таблиц

USE ROLE ACCOUNTADMIN;

-- ─── 1. Два разных механизма, их постоянно путают ─────────
--
--   Time Travel                          Fail-safe
--   ───────────────────────────────      ─────────────────────────────
--   0-90 дней, настраивается тобой       ровно 7 дней, не настраивается
--   доступен через SQL (AT / BEFORE)     доступен только через саппорт
--   для восстановления после ошибки      для восстановления после аварии
--   оплачивается как хранение            оплачивается как хранение
--
-- Fail-safe начинается там, где кончился Time Travel.
-- Восстановление из него — это тикет в Snowflake Support, не запрос.

-- ─── 2. Типы таблиц: ретенция и наличие Fail-safe ─────────
--
--   Тип         Time Travel      Fail-safe   Когда применять
--   ─────────   ──────────────   ─────────   ────────────────────────
--   PERMANENT   0-90 дней        7 дней      всё, что нельзя потерять
--   TRANSIENT   0-1 день         нет         staging, промежуточные слои
--   TEMPORARY   0-1 день         нет         живёт до конца сессии
--
-- TRANSIENT — прямой способ срезать счёт за хранение на слоях,
-- которые всегда можно пересобрать из raw.

CREATE TRANSIENT TABLE staging.stg_orders_tmp AS SELECT * FROM raw.orders;

-- ─── 3. Настройка ретенции на разных уровнях ──────────────
ALTER DATABASE analytics_db SET DATA_RETENTION_TIME_IN_DAYS = 7;
ALTER SCHEMA   staging      SET DATA_RETENTION_TIME_IN_DAYS = 1;
ALTER TABLE    raw.orders   SET DATA_RETENTION_TIME_IN_DAYS = 30;

-- Значение наследуется сверху вниз и переопределяется на любом уровне.
SELECT table_schema, table_name, retention_time
FROM analytics_db.information_schema.tables
WHERE table_type = 'BASE TABLE'
ORDER BY retention_time DESC;

-- ─── 4. Ретенция 0 отключает и Time Travel, и UNDROP ──────
-- Экономия на dev-схемах, но DROP становится необратимым.
ALTER SCHEMA scratch SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- ─── 5. Куда уходят деньги ────────────────────────────────
SELECT
    SUM(active_bytes)      / POW(1024, 3) AS active_gb,
    SUM(time_travel_bytes) / POW(1024, 3) AS time_travel_gb,
    SUM(failsafe_bytes)    / POW(1024, 3) AS failsafe_gb
FROM snowflake.account_usage.table_storage_metrics
WHERE deleted = FALSE;

-- Если time_travel_gb сопоставим с active_gb — где-то таблица
-- с высокой ретенцией, которую переписывают целиком каждый день.
-- Лечится не уменьшением ретенции, а incremental-моделью в dbt.
