-- snowflake_setup/12_streams.sql
-- Days 94-96: Streams — CDC внутри Snowflake
-- Запуск: Snowflake Worksheet или SnowSQL
-- Расширяет 07_streams_cdc.sql из дней 71-75.

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- ─── 1. Что такое stream ──────────────────────────────────
-- Stream НЕ хранит данные. Это указатель (offset) на точку во времени
-- плюс правило: «покажи разницу между тем состоянием и текущим».
-- Хранение стрима ~ 0 байт. Работает он поверх Time Travel: тот же
-- механизм неизменяемых micro-partitions, что в 09_time_travel.sql.

CREATE OR REPLACE STREAM orders_stream_stg ON TABLE orders
    COMMENT = 'CDC для staging-загрузки. Один стрим = один потребитель';

-- Сразу после создания стрим ПУСТ: offset = «сейчас».
SELECT COUNT(*) AS rows_in_fresh_stream FROM orders_stream_stg;   -- 0

-- ─── 2. Три метаданных-колонки ────────────────────────────
-- METADATA$ACTION    — INSERT | DELETE. UPDATE отдельным значением НЕ бывает.
-- METADATA$ISUPDATE  — TRUE, если пара DELETE+INSERT произошла из UPDATE.
-- METADATA$ROW_ID    — стабильный id версии строки.
SELECT
    order_id,
    amount,
    METADATA$ACTION    AS action,
    METADATA$ISUPDATE  AS is_update,
    METADATA$ROW_ID    AS row_id
FROM orders_stream_stg
ORDER BY order_id;

-- Один UPDATE приезжает ДВУМЯ строками:
--   DELETE + ISUPDATE=TRUE  → как было
--   INSERT + ISUPDATE=TRUE  → как стало
-- Отсюда типичный баг: наивный INSERT ... SELECT без фильтра по
-- METADATA$ACTION задваивает строки.

-- ─── 3. Стрим — это diff, а не журнал ─────────────────────
-- Строка, вставленная и удалённая между двумя чтениями стрима,
-- не появится в нём вообще. Net change, не changelog.
-- Нужен полный журнал → CHANGES или таблица-аудит, не стрим:
SELECT *
FROM orders
CHANGES (INFORMATION => APPEND_ONLY)
AT (OFFSET => -60 * 60);

-- ─── 4. Offset двигает DML, а не SELECT ───────────────────
-- SELECT из стрима можно делать сколько угодно — offset стоит.
-- Двигает его только успешно закоммиченная транзакция, где стрим
-- прочитан внутри DML. Ошибка в транзакции → offset не сдвинулся.
BEGIN;
INSERT INTO staging.stg_orders (order_id, user_id, amount, city, order_date)
SELECT order_id, user_id, amount, city, updated_at::DATE
FROM orders_stream_stg
WHERE METADATA$ACTION = 'INSERT'
  AND status = 'completed';
COMMIT;

SELECT COUNT(*) AS rows_after_consume FROM orders_stream_stg;   -- 0

-- ─── 5. Один стрим = один потребитель ─────────────────────
-- Два разных потребителя одной таблицы → ДВА стрима.
-- Иначе тот, кто прочитал вторым, не увидит ничего.
CREATE OR REPLACE STREAM orders_stream_audit ON TABLE orders
    COMMENT = 'Второй потребитель: аудит. Свой независимый offset';

-- ─── 6. Типы стримов ──────────────────────────────────────
-- STANDARD    — INSERT/UPDATE/DELETE. По умолчанию.
-- APPEND_ONLY — только INSERT. Дешевле и быстрее: не надо
--               сопоставлять старые и новые micro-partitions.
--               Идеален для событийных, никогда не обновляемых таблиц.
-- INSERT_ONLY — только для внешних таблиц (external tables).
CREATE OR REPLACE STREAM orders_stream_events ON TABLE orders
    APPEND_ONLY = TRUE;

-- Стрим можно повесить и на VIEW, и на directory table стейджа:
CREATE OR REPLACE STREAM completed_orders_stream ON VIEW v_completed_orders;

-- ─── 7. Протухание (stale) — главная эксплуатационная боль ─
-- Если стрим не читали дольше, чем DATA_RETENTION_TIME_IN_DAYS
-- исходной таблицы, он становится STALE. Прочитать его уже нельзя —
-- только пересоздать, потеряв изменения.
SHOW STREAMS LIKE 'orders_stream%';   -- колонки stale / stale_after

SELECT SYSTEM$STREAM_HAS_DATA('orders_stream_stg') AS has_data;

-- Лечение: поднять ретенцию на исходной таблице и читать регулярно.
ALTER TABLE orders SET DATA_RETENTION_TIME_IN_DAYS = 14;
