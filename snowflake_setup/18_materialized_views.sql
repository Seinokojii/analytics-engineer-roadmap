-- snowflake_setup/18_materialized_views.sql
-- Days 97-98: Materialized Views против dbt incremental

USE WAREHOUSE COMPUTE_WH;
USE DATABASE ANALYTICS_DB;
USE SCHEMA ANALYTICS;

-- ── 1. Что такое MV в Snowflake ────────────────────────────
-- Не «сохранённый запрос», а физически материализованный результат,
-- который Snowflake сам поддерживает в актуальном состоянии
-- при изменении базовой таблицы. Обновление — фоновый сервис
-- с собственной строкой в счёте.

CREATE MATERIALIZED VIEW mv_daily_city_sales AS
SELECT
    order_date,
    city,
    count(*)     AS orders_cnt,
    sum(amount)  AS revenue
FROM raw.orders
GROUP BY order_date, city;

-- ── 2. Ограничения — их много, и они решают выбор ──────────
--   * только ОДНА таблица: никаких JOIN
--   * нельзя UNION, ORDER BY, LIMIT
--   * нельзя вложенные подзапросы и оконные функции
--   * нельзя self-join и нестабильные UDF
--   * нельзя поверх другой MV
--   * доступно только на Enterprise Edition и выше
-- Практически это означает: MV годится для одной агрегации
-- над одной таблицей. Любая витрина со звездой сюда не помещается.

-- ── 3. Главное свойство: прозрачная подстановка ─────────────
-- Оптимизатор сам подставит MV, даже если запрос её не упоминает:
SELECT city, sum(amount) FROM raw.orders
WHERE order_date >= '2026-03-01' GROUP BY city;
-- В Query Profile будет чтение mv_daily_city_sales, а не orders.
-- Это то, чего dbt-модель не умеет в принципе: к ней надо обратиться явно.

-- ── 4. Сколько стоит поддержка ─────────────────────────────
SELECT
    table_name,
    SUM(credits_used) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.MATERIALIZED_VIEW_REFRESH_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY credits DESC;

SHOW MATERIALIZED VIEWS;
SELECT SYSTEM$ESTIMATE_QUERY_ACCELERATION('<query_id>');

-- ── 5. Dynamic Tables — то, что обычно нужно вместо MV ─────
-- Снимают почти все ограничения MV: JOIN можно, окна можно,
-- цепочки можно. Свежесть задаётся декларативно.
CREATE OR REPLACE DYNAMIC TABLE dt_daily_city_sales
    TARGET_LAG = '1 hour'
    WAREHOUSE  = COMPUTE_WH
AS
SELECT o.order_date, c.city, count(*) AS orders_cnt, sum(o.amount) AS revenue
FROM raw.orders o
JOIN raw.customers c ON c.customer_id = o.customer_id
GROUP BY 1, 2;
-- Но прозрачной подстановки у них нет: обращаться надо явно.

-- ── 6. Дерево решений ──────────────────────────────────────
--
--   Одна таблица, простая агрегация, читают часто,
--   запросы переписать нельзя (BI ходит в сырую таблицу)  → MV
--
--   Нужны JOIN / окна / цепочка моделей,
--   обновление по расписанию, нужен git и code review     → dbt incremental
--
--   Нужны JOIN И низкая задержка без оркестратора          → Dynamic Table
--
--   Пересчёт дешёвый, данные небольшие                     → обычная dbt table
--
-- На практике в AE-проекте по умолчанию берётся dbt incremental:
-- он версионируется, тестируется и переносится между платформами.
-- MV — точечная оптимизация под конкретный горячий запрос, не архитектура.

DROP MATERIALIZED VIEW IF EXISTS mv_daily_city_sales;
