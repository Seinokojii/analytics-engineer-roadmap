-- snowflake_setup/20_reader_account.sql
-- Days 99-100: Reader Account — доступ для тех, у кого нет Snowflake

USE ROLE ACCOUNTADMIN;

-- ══ ЗАЧЕМ ══════════════════════════════════════════════════
--
-- Обычный share требует, чтобы у потребителя БЫЛ свой Snowflake
-- аккаунт — он платит за свой compute. Если клиент на Snowflake
-- не сидит (а таких большинство), остаётся Reader Account:
-- аккаунт, который создаёт и оплачивает producer.
--
--   Обычный share      Reader account
--   ─────────────      ──────────────
--   consumer платит    ПРОДЮСЕР платит за весь compute консьюмера
--   за свой warehouse
--   consumer сам       producer администрирует аккаунт целиком
--   админит
--
-- Главный риск понятен из таблицы: клиент запускает тяжёлый
-- запрос — счёт приходит тебе. Поэтому RESOURCE MONITOR
-- настраивается ДО того, как отданы креды, а не после.

-- ── 1. Создать reader account ──────────────────────────────
CREATE MANAGED ACCOUNT acme_reader
    ADMIN_NAME     = 'acme_admin',
    ADMIN_PASSWORD = 'СгенерироватьДлинный!Пароль123',   -- не хранить в git
    TYPE           = READER,
    COMMENT        = 'Reader для ACME Retail, договор 2026-09';

-- В выводе придёт accountName и URL — это единственный раз,
-- когда они показаны. Сохранить сразу.
SHOW MANAGED ACCOUNTS;

-- ── 2. Отдать данные в этот аккаунт ────────────────────────
ALTER SHARE partner_orders_share
    ADD ACCOUNTS = acme_reader
    SHARE_RESTRICTIONS = FALSE;   -- FALSE обязателен для reader account

-- ── 3. Ограничить расходы ДО выдачи доступа ────────────────
-- Выполняется уже внутри reader account.
CREATE WAREHOUSE reader_wh
    WAREHOUSE_SIZE     = XSMALL
    AUTO_SUSPEND       = 60        -- секунд простоя до засыпания
    AUTO_RESUME        = TRUE
    INITIALLY_SUSPENDED = TRUE;

CREATE RESOURCE MONITOR reader_monitor
    WITH CREDIT_QUOTA = 50
    FREQUENCY         = MONTHLY
    START_TIMESTAMP   = IMMEDIATELY
    TRIGGERS
        ON 75  PERCENT DO NOTIFY
        ON 90  PERCENT DO SUSPEND            -- дать дописать текущие
        ON 100 PERCENT DO SUSPEND_IMMEDIATE; -- рубить

ALTER WAREHOUSE reader_wh SET RESOURCE_MONITOR = reader_monitor;

-- ── 4. Настроить доступ внутри reader account ──────────────
CREATE DATABASE acme_data FROM SHARE MYORG.PRODUCER_ACCT.partner_orders_share;
CREATE ROLE acme_analyst;
GRANT IMPORTED PRIVILEGES ON DATABASE acme_data TO ROLE acme_analyst;
GRANT USAGE ON WAREHOUSE reader_wh             TO ROLE acme_analyst;
CREATE USER acme_user
    PASSWORD = 'ВременныйПароль!456'
    DEFAULT_ROLE = acme_analyst
    MUST_CHANGE_PASSWORD = TRUE;
GRANT ROLE acme_analyst TO USER acme_user;

-- ── 5. Ограничения reader account ──────────────────────────
--   • Только чтение shared-данных. Ни своих таблиц, ни загрузки.
--   • Нельзя создавать свои share — перешаривать дальше не выйдет.
--   • Один producer: reader привязан к тому, кто его создал.
--   • Лимит на число reader-аккаунтов зависит от edition.
--
-- Когда выбирать что:
--   Клиент на Snowflake              → обычный share
--   Клиента нет на Snowflake,
--     нужен интерактивный SQL        → reader account + resource monitor
--   Клиенту нужен файл раз в сутки   → не share вообще,
--                                      а COPY INTO @stage в его S3

-- ── 6. Удаление ────────────────────────────────────────────
DROP MANAGED ACCOUNT acme_reader;   -- необратимо, предупредить клиента
