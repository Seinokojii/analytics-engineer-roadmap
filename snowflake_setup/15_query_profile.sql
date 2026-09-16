-- snowflake_setup/15_query_profile.sql
-- Days 97-98: Query Profile — как читать план в Snowflake
-- Запускать в Worksheet по одному блоку.

USE WAREHOUSE COMPUTE_WH;
USE DATABASE ANALYTICS_DB;
USE SCHEMA RAW;

-- ── 1. Где вообще смотреть план ────────────────────────────
-- В UI: History → кликнуть по query → вкладка Query Profile.
-- Это не текстовый EXPLAIN, а граф операторов с процентами.
-- Текстовый план тоже есть:
EXPLAIN USING TEXT
SELECT city, count(*) FROM orders WHERE order_date >= '2026-03-01' GROUP BY city;

-- ── 2. Что читать в первую очередь ─────────────────────────
-- Порядок именно такой, сверху вниз по значимости:
--   a) Самый жирный оператор по % of total — с него начинать всегда.
--   b) Partitions scanned / Partitions total — сколько micro-partitions
--      реально прочитано. 1000/1000 на узком фильтре = отсечение не работает.
--   c) Bytes spilled to local storage — не влезли в память warehouse.
--      Есть spilling → либо warehouse больше, либо объём данных меньше.
--   d) Bytes spilled to remote storage — то же, но уже катастрофа:
--      данные ушли за пределы локального SSD.
--   e) Percentage scanned from cache — сколько взято из warehouse cache.

-- ── 3. То же самое без UI, через ACCOUNT_USAGE ──────────────
-- Латентность вьюхи — до 45 минут, это нормально и задокументировано.
SELECT
    query_id,
    LEFT(query_text, 80)                      AS query_preview,
    warehouse_size,
    total_elapsed_time / 1000                 AS seconds,
    bytes_scanned / POWER(1024, 3)            AS gb_scanned,
    partitions_scanned,
    partitions_total,
    ROUND(100 * partitions_scanned
          / NULLIF(partitions_total, 0), 1)   AS pct_partitions_read,
    bytes_spilled_to_local_storage            AS spill_local,
    bytes_spilled_to_remote_storage           AS spill_remote,
    percentage_scanned_from_cache
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND warehouse_name IS NOT NULL
  AND total_elapsed_time > 10000            -- дольше 10 секунд
ORDER BY total_elapsed_time DESC
LIMIT 50;

-- ── 4. Кандидаты на кластеризацию ──────────────────────────
-- Читаем много партиций, а возвращаем мало строк — классический
-- признак того, что фильтру не на что опереться.
SELECT
    LEFT(query_text, 100)                     AS query_preview,
    partitions_scanned,
    partitions_total,
    rows_produced,
    bytes_scanned
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND partitions_total > 100
  AND partitions_scanned > 0.8 * partitions_total   -- прочитали почти всё
  AND rows_produced < 10000                          -- вернули почти ничего
ORDER BY bytes_scanned DESC
LIMIT 20;

-- ── 5. Антипаттерн, который видно в профиле ─────────────────
-- Функция над колонкой: min/max статистика партиции становится
-- неприменима, Snowflake вынужден читать всё.
-- ПЛОХО — partitions_scanned = partitions_total:
SELECT count(*) FROM orders WHERE YEAR(order_date) = 2026;
-- ХОРОШО — то же множество строк, но отсечение работает:
SELECT count(*) FROM orders
WHERE order_date >= '2026-01-01' AND order_date < '2027-01-01';
-- Правило: колонка слева, чистая, без обёрток. Всё остальное — справа.
