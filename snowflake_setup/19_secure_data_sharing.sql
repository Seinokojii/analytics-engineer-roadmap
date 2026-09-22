-- snowflake_setup/19_secure_data_sharing.sql
-- Days 99-100: Secure Data Sharing — отдать данные, не копируя их
-- Запускать в Worksheet по одному блоку, роль ACCOUNTADMIN.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE COMPUTE_WH;
USE DATABASE ANALYTICS_DB;

-- ══ ЧТО ТАКОЕ SHARE ════════════════════════════════════════
--
-- Share — это НЕ копия данных и НЕ выгрузка. Это именованный
-- объект метаданных, внутри которого лежат гранты на объекты
-- producer'а и список аккаунтов-потребителей.
--
--   Producer                         Consumer
--   ────────                         ────────
--   storage: платит за 1 копию   ←   читает те же micro-partitions
--   compute: НЕ платит               compute: платит за СВОЙ warehouse
--
-- Отсюда три следствия, которые и спрашивают на собеседовании:
--   1. Данные видны потребителю мгновенно после COMMIT producer'а.
--      Нет лага пайплайна, потому что нет пайплайна.
--   2. Потребитель не может писать в shared-объект. Вообще.
--      Read-only — часть модели, а не настройка.
--   3. Storage у producer'а не растёт от числа потребителей.
--      Десять консьюмеров — всё та же одна копия данных.

-- ── 1. Создать share и наполнить его грантами ──────────────
CREATE SHARE partner_orders_share
    COMMENT = 'Заказы партнёров, слой GOLD. Owner: analytics team';

-- Грант на БД и схему — это usage, он не даёт видеть таблицы.
GRANT USAGE ON DATABASE ANALYTICS_DB              TO SHARE partner_orders_share;
GRANT USAGE ON SCHEMA   ANALYTICS_DB.GOLD          TO SHARE partner_orders_share;

-- А вот это уже даёт данные. Гранты — поштучные, никакого ALL.
GRANT SELECT ON TABLE ANALYTICS_DB.GOLD.fct_orders TO SHARE partner_orders_share;
GRANT SELECT ON VIEW  ANALYTICS_DB.GOLD.v_partner_orders TO SHARE partner_orders_share;

-- ── 2. Добавить потребителей ───────────────────────────────
-- Аккаунт в формате ORGNAME.ACCOUNTNAME.
ALTER SHARE partner_orders_share ADD ACCOUNTS = MYORG.ACME_RETAIL;
ALTER SHARE partner_orders_share ADD ACCOUNTS = MYORG.GLOBEX_LOGISTICS;

-- Отозвать доступ — одна строка, мгновенно, без удаления данных.
-- ALTER SHARE partner_orders_share REMOVE ACCOUNTS = MYORG.GLOBEX_LOGISTICS;

-- ── 3. Проверить, что именно отдано ────────────────────────
SHOW SHARES;
DESC SHARE partner_orders_share;          -- список объектов внутри share
SHOW GRANTS TO SHARE partner_orders_share;

-- ══ SECURE VIEW: один share на всех, но каждый видит своё ══
--
-- Обычный VIEW в share отдать НЕЛЬЗЯ — Snowflake это запретит.
-- Причина: через план обычной вьюхи потребитель может вытащить
-- определение и добраться до скрытых строк базовой таблицы.
-- SECURE VIEW не раскрывает определение и отключает те
-- оптимизации, которые могли бы утечь данные через предикаты.
-- Цена — часть оптимизаций отключена, вьюха медленнее.

CREATE OR REPLACE SECURE VIEW ANALYTICS_DB.GOLD.v_partner_orders AS
SELECT
    order_id,
    order_date,
    amount,
    city,
    status
FROM ANALYTICS_DB.GOLD.fct_orders
WHERE partner_account = CURRENT_ACCOUNT();     -- ← ключевая строка

-- CURRENT_ACCOUNT() внутри shared secure view возвращает аккаунт
-- ПОТРЕБИТЕЛЯ, а не producer'а. Один объект обслуживает всех
-- партнёров, и каждый видит только свои строки.
-- Проверять надо именно так, из-под консьюмера:
--   SELECT DISTINCT partner_account FROM shared_db.GOLD.v_partner_orders;
-- Если в выдаче больше одного значения — утечка, чинить немедленно.

-- Альтернатива для аккаунтов одной организации — маппинг-таблица:
CREATE OR REPLACE SECURE VIEW ANALYTICS_DB.GOLD.v_partner_orders_mapped AS
SELECT o.*
FROM ANALYTICS_DB.GOLD.fct_orders o
JOIN ANALYTICS_DB.GOLD.account_map m
  ON o.partner_account = m.partner_account
WHERE m.snowflake_account = CURRENT_ACCOUNT();
-- Маппинг-таблицу в share НЕ добавлять: она нужна только для JOIN
-- внутри secure view и не должна быть видна снаружи.

-- ── 4. Сторона потребителя ─────────────────────────────────
-- Выполняется уже в аккаунте консьюмера, роль ACCOUNTADMIN.
SHOW SHARES;                               -- входящие share видны здесь
DESC SHARE MYORG.PRODUCER_ACCT.partner_orders_share;

CREATE DATABASE partner_data FROM SHARE MYORG.PRODUCER_ACCT.partner_orders_share;
GRANT IMPORTED PRIVILEGES ON DATABASE partner_data TO ROLE ANALYST;

-- Дальше — обычный SQL, и он не отличим от локальных таблиц:
SELECT count(*), sum(amount) FROM partner_data.GOLD.v_partner_orders;

-- А вот это упадёт, и должно упасть:
-- INSERT INTO partner_data.GOLD.fct_orders VALUES (...);
--   → SQL access control error: shared database is read-only

-- ── 5. Ограничения, о которых спрашивают ───────────────────
--   • Потребитель не может: INSERT/UPDATE/DELETE, CREATE TABLE
--     в shared-базе, CLONE shared-объекта, Time Travel по нему.
--   • Shared-таблицу нельзя переименовать/дропнуть у producer'а,
--     пока она в share — сначала REVOKE.
--   • Share не пересекает регионы и облака сам по себе.
--     Для cross-region нужна репликация БД в целевой регион,
--     и вот за неё уже платят трафиком:
--         ALTER DATABASE analytics_db ENABLE REPLICATION
--             TO ACCOUNTS MYORG.EU_ACCOUNT;
--   • Trial-аккаунт не может быть producer'ом.
--   • Изменение DDL у producer'а (добавили колонку) видно
--     потребителю сразу — контракт ломается молча.
--     Отсюда правило: в share кладут VIEW, а не таблицу,
--     тогда вьюха служит стабильным контрактом.

-- ── 6. Мониторинг: кто и сколько читает ────────────────────
SELECT
    consumer_account_name,
    share_name,
    count(*)                       AS queries,
    sum(credits_used)              AS credits_на_стороне_producer
FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2
ORDER BY queries DESC;

-- Листинги и их потребление (для Marketplace/private listings):
SELECT *
FROM SNOWFLAKE.DATA_SHARING_USAGE.LISTING_ACCESS_HISTORY
WHERE query_date >= DATEADD(day, -30, CURRENT_DATE())
ORDER BY query_date DESC
LIMIT 100;
