-- snowflake_setup/16_result_cache.sql
-- Days 97-98: три уровня кеша в Snowflake

USE WAREHOUSE COMPUTE_WH;
USE DATABASE ANALYTICS_DB;
USE SCHEMA RAW;

-- ── Три кеша, которые часто путают ─────────────────────────
--
--   Result Cache      — готовый результат запроса. Живёт 24 часа,
--                       продлевается при каждом повторе, максимум 31 день.
--                       Warehouse вообще не запускается → 0 кредитов.
--                       Общий на весь аккаунт, не на пользователя.
--
--   Warehouse Cache   — прочитанные micro-partitions на локальном SSD
--   (local disk)        конкретного warehouse. Умирает при SUSPEND.
--                       Отсюда правило: слишком агрессивный auto-suspend
--                       экономит копейки и выбрасывает кеш.
--
--   Metadata Cache    — min/max, счётчики строк, NDV. Из него отвечают
--                       SELECT count(*) и SELECT max(col) — без чтения данных.

-- ── 1. Проверить result cache ──────────────────────────────
ALTER SESSION SET USE_CACHED_RESULT = TRUE;   -- по умолчанию и так TRUE

SELECT city, count(*) AS orders_cnt
FROM orders
WHERE order_date >= '2026-01-01'
GROUP BY city;
-- Повторить тот же запрос: в Query Profile будет единственный узел
-- QUERY RESULT REUSE, время ~0 мс, потраченных кредитов — ноль.

-- ── 2. Условия попадания — строже, чем кажется ──────────────
-- Текст запроса должен совпасть ПОБАЙТОВО. Лишний пробел или
-- другой регистр — промах.
-- Ни одна из таблиц не изменилась с момента кеширования.
-- Запрос не содержит недетерминированных функций:
SELECT CURRENT_TIMESTAMP(), count(*) FROM orders;  -- НИКОГДА не кешируется
-- Роль должна иметь те же привилегии на все объекты запроса.

-- ── 3. Честный замер: отключить кеш и сравнить ──────────────
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
SELECT city, count(*) FROM orders WHERE order_date >= '2026-01-01' GROUP BY city;
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
-- Это стандартный приём при бенчмарке: без него меряешь кеш, а не запрос.

-- ── 4. Инвалидация ─────────────────────────────────────────
INSERT INTO orders VALUES (999999, 1, 100.0, 'Oslo', 'new', CURRENT_TIMESTAMP());
-- Любой DML по orders обнуляет result cache для ВСЕХ запросов,
-- которые её читают. Не по строкам — по таблице целиком.

-- ── 5. Сколько запросов реально попадает в кеш ──────────────
SELECT
    CASE WHEN bytes_scanned = 0 AND execution_status = 'SUCCESS'
         THEN 'result_cache_hit' ELSE 'executed' END AS kind,
    count(*)                                          AS queries,
    ROUND(avg(total_elapsed_time), 1)                 AS avg_ms
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND query_type = 'SELECT'
GROUP BY 1;
-- Низкий процент попаданий на дашборде = дашборд шлёт запросы
-- с меняющимся текстом (таймстемп в параметрах, случайный alias).
