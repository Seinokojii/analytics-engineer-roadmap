-- snowflake_setup/17_clustering_search_optimization.sql
-- Days 97-98: Clustering Keys + Search Optimization Service

USE WAREHOUSE COMPUTE_WH;
USE DATABASE ANALYTICS_DB;
USE SCHEMA RAW;

-- ══ ЧАСТЬ 1. CLUSTERING KEYS ═══════════════════════════════
--
-- Micro-partition — 50-500 МБ несжатых данных, колоночное хранение,
-- неизменяемый блок. Для каждой партиции Snowflake держит min/max
-- по каждой колонке. Фильтр по колонке → партиции, чей диапазон
-- не пересекается с условием, не читаются вообще. Это pruning.
--
-- Данные ложатся в партиции в порядке загрузки. Если грузили
-- по дням — по дате они уже отсортированы, и clustering key не нужен.
-- Если грузили вперемешку — каждая партиция содержит весь диапазон
-- дат, min/max бесполезны, отсекать нечего.

-- ── 1. Диагностика ДО решения ──────────────────────────────
SELECT SYSTEM$CLUSTERING_INFORMATION('orders', '(order_date)');
-- Смотреть в выводе:
--   average_overlaps  — на скольких партициях в среднем лежит значение
--   average_depth     — сколько партиций придётся прочитать ради одного
--                       значения. 1.0 = идеально, больше 10 = плохо
--   partition_depth_histogram — распределение; длинный хвост справа
--                       означает, что часть значений размазана по всей таблице

-- ── 2. Назначить ключ ──────────────────────────────────────
ALTER TABLE orders CLUSTER BY (order_date);
-- Несколько колонок — строго от низкой кардинальности к высокой:
ALTER TABLE orders CLUSTER BY (order_date, city);
-- Три-четыре колонки — предел; дальше ключ перестаёт работать.
-- Выражение вместо колонки — законно и часто дешевле полной колонки:
ALTER TABLE events CLUSTER BY (TO_DATE(event_ts));

-- ── 3. Чем за это платят ───────────────────────────────────
-- Automatic Clustering — фоновый сервис, отдельная строка в счёте.
SELECT
    table_name,
    SUM(credits_used)                       AS credits,
    SUM(num_bytes_reclustered) / POWER(1024, 3) AS gb_reclustered
FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY credits DESC;
-- Таблица с частым DML пересобирается постоянно. Бывает, что
-- кластеризация стоит дороже, чем экономит. Это надо считать, а не верить.

-- ── 4. Когда НЕ кластеризовать ─────────────────────────────
--   * таблица меньше нескольких сотен партиций — эффекта нет
--   * таблица часто перезаписывается целиком — дешевле грузить отсортированно
--   * фильтры каждый раз по разным колонкам — ключ поможет одному запросу
--     из пяти, а платить придётся всегда
--   * колонка почти уникальна (order_id) — это задача Search Optimization

-- ══ ЧАСТЬ 2. SEARCH OPTIMIZATION SERVICE ═══════════════════
--
-- Clustering помогает диапазонам. SOS — точечным lookup:
-- «дай строку по идентификатору» на таблице в миллиарды строк.
-- Служба строит и обслуживает отдельную структуру поиска.

ALTER TABLE orders ADD SEARCH OPTIMIZATION;
-- Точечно, по колонкам — обычно то, что нужно:
ALTER TABLE orders ADD SEARCH OPTIMIZATION ON EQUALITY(order_id, customer_email);
ALTER TABLE events ADD SEARCH OPTIMIZATION ON SUBSTRING(url);
ALTER TABLE events ADD SEARCH OPTIMIZATION ON EQUALITY(payload:user_id);  -- VARIANT

SHOW TABLES LIKE 'orders';   -- колонки search_optimization / _progress / _bytes

-- Запрос, ради которого всё затевалось:
SELECT * FROM orders WHERE order_id = 'A-7739201';
-- До SOS: partitions_scanned = partitions_total.
-- После:  единицы партиций.

SELECT
    SUM(credits_used)                AS credits,
    SUM(num_bytes) / POWER(1024, 3)  AS gb_indexed
FROM SNOWFLAKE.ACCOUNT_USAGE.SEARCH_OPTIMIZATION_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP());

ALTER TABLE orders DROP SEARCH OPTIMIZATION;

-- ── Что выбрать: короткое дерево решений ───────────────────
--   Фильтр по диапазону дат, много строк в ответе   → Clustering Key
--   Точечный поиск по ключу, мало строк в ответе    → Search Optimization
--   И то, и другое на одной таблице                 → можно вместе, но
--                                                     сначала посчитать счёт
--   Таблица маленькая                               → ничего не нужно
