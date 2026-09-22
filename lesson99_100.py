#!/usr/bin/env python3
"""
lesson99_100.py — Days 99-100: Data Sharing + Marketplace

Запуск:
    python lesson99_100.py

Закрывает Неделю 13 и блок Snowflake Advanced. Принцип прежний:
Snowflake-аккаунта нет, поэтому .sql пишутся готовыми к запуску
в Worksheet, а механика отрабатывается локально на DuckDB.

Что делает:
  1. Пишет три SQL-скрипта под реальный Snowflake в snowflake_setup/
  2. Строит producer-базу: 3 млн заказов трёх партнёров
  3. Share как объект метаданных: каталог SHARES / GRANTS / CONSUMERS,
     добавление таблицы в share — запись в метаданные, а не копия
  4. Secure View: фильтрация строк по потребителю на стороне сервера,
     проверка изоляции — acme не видит строк globex
  5. Копия против ссылки: замер байтов и секунд, а потом главное —
     producer дописывает строки, share их видит, копия протухла
  6. Контракт share: потребитель читает, но не пишет — проверено ошибкой
  7. Marketplace: внешний датасет подключается как read-only база,
     джойнится с собственными данными, ETL нет вообще
  8. Кладёт CSV в reports/ + блок «На собеседовании»

Что здесь симулируется хуже оригинала — честно:
  Главного свойства Secure Data Sharing локально нет и быть не может:
  в Snowflake consumer читает micro-partitions producer'а через слой
  метаданных, платя при этом за СВОЙ warehouse, а producer платит
  только за storage. Здесь нет ни разделения storage/compute,
  ни двух аккаунтов, ни биллинга — есть только следствие:
  данные не копируются и видны мгновенно.
  Reader Account не симулируется никак — это провижининг аккаунта
  на стороне Snowflake. Скрипт 20 написан, но не выполнялся.
  Marketplace-листинг заменён локальным файлом: подписка на реальный
  листинг — действие в UI чужого аккаунта.
  READ_ONLY в DuckDB — свойство подключения к файлу, в Snowflake же
  запрет на запись в shared-объект прошит в саму модель share.
  Эффект совпадает, механизм разный.
"""

import csv
import time
from datetime import datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
REPORTS_DIR = PROJECT_ROOT / "reports"
SHARE_DIR = SNOWFLAKE_DIR / "sharing_demo"

SNOWFLAKE_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
SHARE_DIR.mkdir(exist_ok=True)

PRODUCER_DB = SHARE_DIR / "producer_account.duckdb"
CONSUMER_DB = SHARE_DIR / "consumer_account.duckdb"
COPY_DB = SHARE_DIR / "consumer_copy.duckdb"
MARKET_DB = SHARE_DIR / "marketplace_weather.duckdb"

TODAY = datetime.now().strftime("%Y-%m-%d")

SEP = "=" * 62

# 3 млн строк: достаточно, чтобы копия занимала заметные мегабайты
# и копировалась заметные секунды — иначе разница «копия vs ссылка»
# не видна и звучит как лозунг.
N_ROWS = 3_000_000
PARTNERS = ("ACME_RETAIL", "GLOBEX_LOGISTICS", "INITECH_BANK")


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")


def thousands(n) -> str:
    """Разряды неразрывным пробелом. Не .replace(',', ' ') по абзацу —
    тот вариант съедал запятые в русском тексте (баг дня 97-98)."""
    return f"{n:,}".replace(",", " ")


def mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def write_csv(path: Path, header, rows) -> Path:
    # lineterminator обязателен: csv.writer по умолчанию пишет \r\n
    # даже на Linux. Ловилось уже дважды — в 03927efc и 03068247.
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")
    return path


# ═══════════════════════════════════════════════════════════
#  STEP 1 — SQL под реальный Snowflake
# ═══════════════════════════════════════════════════════════

SECURE_SHARING_SQL = """\
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
"""

READER_ACCOUNT_SQL = """\
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
"""

MARKETPLACE_SQL = """\
-- snowflake_setup/21_marketplace.sql
-- Days 99-100: Snowflake Marketplace — чужой датасет без ETL

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE COMPUTE_WH;

-- ══ ЧТО ЭТО ════════════════════════════════════════════════
--
-- Marketplace — витрина share'ов. Подписка на листинг создаёт
-- в твоём аккаунте базу, которая является ссылкой на данные
-- вендора. Технически это тот же Secure Data Sharing.
--
-- Что это меняет для Analytics Engineer практически:
--   Было:  вендор → API → Airbyte → S3 → COPY INTO → dbt → модель
--          (пайплайн, который надо писать, мониторить и чинить)
--   Стало: подписка → SELECT
--          (нет пайплайна — нечему ломаться в 3 часа ночи)
--
-- Три типа листингов:
--   Free        — бесплатно, мгновенно, без переговоров
--   Paid        — подписка, счёт через Snowflake
--   Personalized— запрос вендору, он отдаёт срез под тебя

-- ── 1. Подписаться ─────────────────────────────────────────
-- Данные → Marketplace → найти листинг → Get.
-- В диалоге задаётся имя локальной базы и роли, которым дать доступ.
-- SQL-эквивалент для листинга, у которого известен global name:
CREATE DATABASE weather_source
    FROM LISTING 'GZTSZAS2KF7';          -- global name листинга
GRANT IMPORTED PRIVILEGES ON DATABASE weather_source TO ROLE ANALYST;

SHOW DATABASES LIKE 'weather%';
SHOW SCHEMAS IN DATABASE weather_source;
SHOW TABLES IN SCHEMA weather_source.PUBLIC;

-- ── 2. Первым делом — проверить свежесть, а не строить витрину ──
-- Листинг может обновляться раз в сутки, а может раз в квартал.
-- Это выясняется до того, как на него завязана модель.
SELECT
    max(date_valid_std)                                  AS last_date,
    datediff('day', max(date_valid_std), CURRENT_DATE()) AS дней_отставания,
    count(*)                                             AS rows_total
FROM weather_source.PUBLIC.history_day;

-- ── 3. Джойн с собственными данными ────────────────────────
-- Ради этого всё и затевалось: внешние данные соединяются
-- с внутренними одним запросом, оба лежат в одном движке.
-- ВНИМАНИЕ на зерно. Погода лежит с зерном день-город, заказы —
-- с зерном заказа. Джойн погоды прямо на fct_orders умножает
-- sum(precipitation) на число заказов за день: запрос отработает,
-- цифра будет завышена в сотни раз, и ни один тест не сработает.
-- Сначала свести заказы к зерну справочника, потом джойнить.
WITH daily AS (
    SELECT
        order_date,
        city,
        count(*)      AS orders,
        sum(amount)   AS revenue
    FROM ANALYTICS_DB.GOLD.fct_orders
    WHERE order_date >= DATEADD(month, -3, CURRENT_DATE())
    GROUP BY 1, 2
)
SELECT
    d.order_date,
    d.city,
    d.orders,
    d.revenue,
    w.avg_temperature_air_2m_f AS avg_temp_f,
    w.tot_precipitation_in     AS precipitation_in
FROM daily d
LEFT JOIN weather_source.PUBLIC.history_day w
       ON d.city = w.city_name
      AND d.order_date = w.date_valid_std
ORDER BY 1 DESC, d.revenue DESC;

-- ── 4. Как это заворачивается в dbt ────────────────────────
-- Marketplace-база объявляется обычным source. Ключевое —
-- freshness: пайплайна нет, но данные всё равно могут протухнуть,
-- и узнать об этом надо тестом, а не от менеджера.
--
--   # models/staging/_sources.yml
--   sources:
--     - name: weather
--       database: weather_source
--       schema: PUBLIC
--       freshness:
--         warn_after:  {count: 2, period: day}
--         error_after: {count: 7, period: day}
--       loaded_at_field: date_valid_std::timestamp
--       tables:
--         - name: history_day
--
--   -- models/staging/stg_weather.sql
--   select
--       city_name                  as city,
--       date_valid_std             as weather_date,
--       avg_temperature_air_2m_f   as avg_temp_f,
--       tot_precipitation_in       as precipitation_in
--   from {{ source('weather', 'history_day') }}
--
-- Правило: НИКОГДА не ссылаться на marketplace-таблицу из mart-модели
-- напрямую. Только через staging-слой. Вендор меняет схему без
-- предупреждения, и тогда чинится один stg-файл, а не двадцать витрин.

-- ── 5. Сколько это стоит ───────────────────────────────────
--   Storage за подписку          — 0. Данные лежат у вендора.
--   Compute за запросы           — твой, по обычному тарифу.
--   Сам листинг                  — 0 для free, подписка для paid.
--   Cross-region                 — вот тут внимательно:
--     если листинг в другом регионе, Snowflake предложит
--     auto-fulfillment, и за репликацию платишь ты.
SELECT *
FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
ORDER BY bytes_transferred DESC;

-- ── 6. Стать поставщиком ───────────────────────────────────
-- Provider Studio: профиль организации, листинг, share внутрь него.
-- Private listing — тот же механизм, но виден только названным
-- аккаунтам. На практике это основной способ шарить данные
-- между командами одной компании, живущими в разных аккаунтах:
-- лучше share'а тем, что у листинга есть описание, sample-запросы
-- и версионирование.
"""


def step1_snowflake_sql():
    banner("STEP 1", "SQL под реальный Snowflake")
    write_utf8(SNOWFLAKE_DIR / "19_secure_data_sharing.sql", SECURE_SHARING_SQL)
    write_utf8(SNOWFLAKE_DIR / "20_reader_account.sql", READER_ACCOUNT_SQL)
    write_utf8(SNOWFLAKE_DIR / "21_marketplace.sql", MARKETPLACE_SQL)
    print("""
  Эти три скрипта НЕ выполнялись: аккаунта нет. Они написаны
  под запуск в Worksheet и проверены только глазами.
  Всё, что ниже, — локальная механика на DuckDB.""")


# ═══════════════════════════════════════════════════════════
#  STEP 2 — producer-аккаунт
# ═══════════════════════════════════════════════════════════

def step2_build_producer(con):
    banner("STEP 2", "Producer: 3 млн заказов трёх партнёров")

    partners_sql = "[" + ", ".join(f"'{p}'" for p in PARTNERS) + "]"
    start = time.perf_counter()
    con.execute(f"""
        CREATE OR REPLACE TABLE fct_orders AS
        SELECT
            i                                              AS order_id,
            {partners_sql}[1 + (i % 3)]                    AS partner_account,
            DATE '2026-01-01' + INTERVAL (i % 265) DAY     AS order_date,
            ROUND(20 + (i * 7919 % 48000) / 100.0, 2)      AS amount,
            ['Bishkek','Almaty','Tashkent','Astana','Osh'][1 + (i % 5)] AS city,
            ['delivered','shipped','pending','cancelled'][1 + (i % 4)]  AS status,
            'cust_' || (i % 90000) || '@example.com'       AS customer_email
        FROM range({N_ROWS}) t(i)
    """)
    con.execute("CHECKPOINT")
    build_s = time.perf_counter() - start

    rows = con.execute("""
        SELECT partner_account, count(*), round(sum(amount), 2)
        FROM fct_orders GROUP BY 1 ORDER BY 1
    """).fetchall()

    print(f"  Построено за {build_s:.1f} с, файл {mb(PRODUCER_DB):.1f} МБ\n")
    print(f"  {'partner_account':<20}{'строк':>12}{'выручка':>16}")
    print("  " + "-" * 48)
    for p, c, s in rows:
        print(f"  {p:<20}{thousands(c):>12}{thousands(int(s)):>16}")
    print(f"""
  В Snowflake это таблица в GOLD-слое producer'а. Партнёры —
  отдельные Snowflake-аккаунты, и каждому должны быть видны
  только его строки. Ключевой вопрос дня: как отдать им данные,
  не делая три копии и не строя три пайплайна.""")
    return rows


# ═══════════════════════════════════════════════════════════
#  STEP 3 — share как объект метаданных
# ═══════════════════════════════════════════════════════════

def step3_share_catalog(con):
    banner("STEP 3", "Share — это метаданные, а не данные")

    # Каталог share'ов строится теми же тремя сущностями, что и в
    # Snowflake: сам share, гранты внутрь него и список аккаунтов.
    con.execute("""
        CREATE OR REPLACE TABLE shares (
            share_name VARCHAR, created_at TIMESTAMP, comment VARCHAR
        );
        CREATE OR REPLACE TABLE share_grants (
            share_name VARCHAR, privilege VARCHAR,
            object_type VARCHAR, object_name VARCHAR
        );
        CREATE OR REPLACE TABLE share_consumers (
            share_name VARCHAR, consumer_account VARCHAR, added_at TIMESTAMP
        );
    """)

    size_before = mb(PRODUCER_DB)
    start = time.perf_counter()
    con.execute("""
        INSERT INTO shares VALUES
            ('partner_orders_share', now(), 'Заказы партнёров, слой GOLD');
        INSERT INTO share_grants VALUES
            ('partner_orders_share', 'USAGE',  'DATABASE', 'ANALYTICS_DB'),
            ('partner_orders_share', 'USAGE',  'SCHEMA',   'ANALYTICS_DB.GOLD'),
            ('partner_orders_share', 'SELECT', 'VIEW',     'GOLD.v_partner_orders');
    """)
    con.executemany(
        "INSERT INTO share_consumers VALUES (?, ?, now())",
        [("partner_orders_share", p) for p in PARTNERS[:2]],
    )
    con.execute("CHECKPOINT")
    grant_s = time.perf_counter() - start
    size_after = mb(PRODUCER_DB)

    print(f"""  Создан share, выданы 3 гранта, добавлены 2 потребителя.
  Время:      {grant_s * 1000:.1f} мс
  Файл до:    {size_before:.2f} МБ
  Файл после: {size_after:.2f} МБ
  Прирост:    {(size_after - size_before) * 1024:.0f} КБ на 3 млн отданных строк

  Вот суть Secure Data Sharing: отдать 3 млн строк стоило доли
  секунды и долей процента файла, потому что не двинулось ни одной
  строки данных — двинулась запись в каталоге. Десятый потребитель
  обойдётся ровно в ту же строку.

  Честная оговорка про прирост: почти весь он — не «вес share»,
  а гранулярность блоков DuckDB под три новые таблицы каталога.
  Сам факт share весит десятки байт. Сравнивать надо не с нулём,
  а с альтернативой — тремя копиями по 14 МБ, которые появятся
  в STEP 5.""")

    print("\n  DESC SHARE partner_orders_share:")
    print(f"  {'privilege':<10}{'object_type':<12}{'object_name'}")
    print("  " + "-" * 52)
    for pr, ot, on in con.execute(
        "SELECT privilege, object_type, object_name FROM share_grants"
    ).fetchall():
        print(f"  {pr:<10}{ot:<12}{on}")

    return grant_s * 1000, (size_after - size_before) * 1024


# ═══════════════════════════════════════════════════════════
#  STEP 4 — secure view и изоляция строк
# ═══════════════════════════════════════════════════════════

def step4_secure_view(con):
    banner("STEP 4", "Secure View: один объект, каждый видит своё")

    # getvariable('current_account') — локальный дублёр CURRENT_ACCOUNT().
    # В Snowflake эта функция внутри shared secure view возвращает
    # аккаунт ПОТРЕБИТЕЛЯ; здесь роль потребителя играет переменная
    # сессии, которую мы переключаем руками.
    con.execute("SET VARIABLE current_account = 'PRODUCER_ACCT'")
    con.execute("""
        CREATE OR REPLACE VIEW v_partner_orders AS
        SELECT order_id, order_date, amount, city, status
        FROM fct_orders
        WHERE partner_account = getvariable('current_account')
    """)

    print("  Определение вьюхи одно на всех:")
    print("      WHERE partner_account = CURRENT_ACCOUNT()\n")
    print(f"  {'потребитель':<20}{'видит строк':>14}{'своя доля':>12}")
    print("  " + "-" * 46)

    results = []
    for partner in PARTNERS:
        con.execute(f"SET VARIABLE current_account = '{partner}'")
        seen = con.execute("SELECT count(*) FROM v_partner_orders").fetchone()[0]
        own = con.execute(
            "SELECT count(*) FROM fct_orders WHERE partner_account = ?", [partner]
        ).fetchone()[0]
        mark = "OK" if seen == own else "УТЕЧКА"
        results.append((partner, seen, own, mark))
        print(f"  {partner:<20}{thousands(seen):>14}{mark:>12}")

    # Главная проверка: не «сколько видит», а «не видит ли чужого».
    con.execute(f"SET VARIABLE current_account = '{PARTNERS[0]}'")
    leaked = con.execute("""
        SELECT count(*) FROM v_partner_orders o
        WHERE o.order_id IN (
            SELECT order_id FROM fct_orders WHERE partner_account <> ?
        )
    """, [PARTNERS[0]]).fetchone()[0]

    print(f"""
  Проверка изоляции: {PARTNERS[0]} видит чужих строк — {leaked}.
  Это и есть тест, который надо гонять после каждой правки вьюхи.
  Считать «свои строки на месте» недостаточно: утечка выглядит
  как лишние строки, а не как недостача.

  Почему в share требуется именно SECURE VIEW:
    обычная вьюха раскрывает своё определение консьюмеру и
    допускает оптимизации, через которые данные утекают косвенно.
    Классика — предикат с функцией, которая падает на «чужих»
    значениях: оптимизатор проталкивает его ДО фильтра доступа,
    и текст ошибки выдаёт содержимое скрытых строк.
    SECURE отключает проталкивание. Платим скоростью.""")
    return results, leaked


# ═══════════════════════════════════════════════════════════
#  STEP 5 — копия против ссылки
# ═══════════════════════════════════════════════════════════

def step5_copy_vs_share(con):
    banner("STEP 5", "Копия против ссылки: байты, секунды и свежесть")

    for p in (COPY_DB, CONSUMER_DB):
        if p.exists():
            p.unlink()

    # Оба аккаунта живут в одном процессе: producer — основная база,
    # consumer — приаттаченная. DuckDB не разрешает открыть один файл
    # двумя подключениями, и это как раз то место, где локальная
    # модель расходится с облаком: там два независимых аккаунта.
    con.execute(f"ATTACH '{CONSUMER_DB}' AS consumer_acct")
    con.execute(f"ATTACH '{COPY_DB}' AS consumer_copy")

    # ── Путь А: выгрузка и копия (как жили до share) ──────────
    start = time.perf_counter()
    con.execute("""
        CREATE TABLE consumer_copy.fct_orders_snapshot AS
        SELECT * FROM fct_orders WHERE partner_account = 'ACME_RETAIL'
    """)
    con.execute("CHECKPOINT consumer_copy")
    copy_s = time.perf_counter() - start
    copy_mb = mb(COPY_DB)

    # ── Путь Б: share — ссылка на те же данные ────────────────
    # В базе потребителя не появляется ни одной строки: создаётся
    # только объект, указывающий на storage producer'а.
    con.execute("SET VARIABLE current_account = 'ACME_RETAIL'")
    start = time.perf_counter()
    con.execute("""
        CREATE VIEW consumer_acct.v_partner_orders AS
        SELECT order_id, order_date, amount, city, status
        FROM producer_account.fct_orders
        WHERE partner_account = getvariable('current_account')
    """)
    con.execute("CHECKPOINT consumer_acct")
    share_s = time.perf_counter() - start
    share_mb = mb(CONSUMER_DB)

    copy_rows = con.execute(
        "SELECT count(*) FROM consumer_copy.fct_orders_snapshot").fetchone()[0]
    share_rows = con.execute(
        "SELECT count(*) FROM consumer_acct.v_partner_orders").fetchone()[0]

    print(f"""  {'':<26}{'копия':>14}{'share':>14}
  {'-' * 54}
  {'время создания':<26}{copy_s:>13.2f}с{share_s * 1000:>12.0f}мс
  {'занято у потребителя':<26}{copy_mb:>12.1f}МБ{share_mb:>12.2f}МБ
  {'строк видно':<26}{thousands(copy_rows):>14}{thousands(share_rows):>14}""")

    # ── Теперь главное: producer дописывает данные ────────────
    print("\n  Producer дописывает 50 000 свежих заказов ACME_RETAIL...")
    con.execute(f"""
        INSERT INTO fct_orders
        SELECT
            {N_ROWS} + i, 'ACME_RETAIL',
            DATE '2026-09-23',
            ROUND(20 + (i * 31 % 48000) / 100.0, 2),
            ['Bishkek','Almaty','Tashkent','Astana','Osh'][1 + (i % 5)],
            'pending',
            'cust_' || (i % 90000) || '@example.com'
        FROM range(50000) t(i)
    """)
    con.execute("CHECKPOINT")

    copy_after = con.execute(
        "SELECT count(*) FROM consumer_copy.fct_orders_snapshot").fetchone()[0]
    share_after = con.execute(
        "SELECT count(*) FROM consumer_acct.v_partner_orders").fetchone()[0]

    print(f"""
  {'':<26}{'копия':>14}{'share':>14}
  {'-' * 54}
  {'было':<26}{thousands(copy_rows):>14}{thousands(share_rows):>14}
  {'стало':<26}{thousands(copy_after):>14}{thousands(share_after):>14}
  {'отставание':<26}{thousands(share_after - copy_after):>14}{'0':>14}

  Копия протухла в момент COMMIT'а producer'а и останется
  протухшей до следующего запуска пайплайна. Share отстаёт на ноль
  строк, и это не потому, что он быстрый, а потому что синхронизации
  там нет как этапа: consumer читает те же файлы.

  Что здесь врёт по сравнению со Snowflake: у нас один процесс и
  один диск. В Snowflake consumer читает micro-partitions producer'а
  из чужого storage через слой метаданных, платя за свой warehouse.
  Эффект тот же, механизм на порядок сложнее.""")

    return {
        "copy_s": copy_s, "share_s": share_s,
        "copy_mb": copy_mb, "share_mb": share_mb,
        "copy_before": copy_rows, "share_before": share_rows,
        "copy_after": copy_after, "share_after": share_after,
    }


# ═══════════════════════════════════════════════════════════
#  STEP 6 — Marketplace
# ═══════════════════════════════════════════════════════════

def step6_marketplace(con):
    banner("STEP 6", "Marketplace: чужой датасет без единой строки ETL")

    # Файл вендора собирается отдельным подключением и закрывается —
    # дальше он для нас чужой и приаттачен только на чтение.
    if MARKET_DB.exists():
        MARKET_DB.unlink()
    vendor = duckdb.connect(str(MARKET_DB))
    vendor.execute("""
        CREATE TABLE history_day AS
        SELECT
            ['Bishkek','Almaty','Tashkent','Astana','Osh'][1 + (i % 5)] AS city_name,
            DATE '2026-01-01' + INTERVAL (i / 5) DAY        AS date_valid_std,
            ROUND(10 + 45 * sin((i / 5) / 58.0) + (i % 7), 1) AS avg_temperature_air_2m_f,
            ROUND(CASE WHEN (i * 13) % 11 = 0
                       THEN ((i * 17) % 90) / 100.0 ELSE 0 END, 2) AS tot_precipitation_in
        FROM range(1325) t(i)
    """)
    vendor.execute("CHECKPOINT")
    vendor.close()

    start = time.perf_counter()
    con.execute(f"ATTACH '{MARKET_DB}' AS weather_source (READ_ONLY)")
    subscribe_ms = (time.perf_counter() - start) * 1000

    freshness = con.execute("""
        SELECT max(date_valid_std)::DATE,
               datediff('day', max(date_valid_std), DATE '2026-09-23'),
               count(*)
        FROM weather_source.history_day
    """).fetchone()

    print(f"""  Подписка выполнена за {subscribe_ms:.0f} мс, storage у нас: 0 байт.
  Ни Airbyte, ни stage, ни COPY INTO, ни schedule — ничего.

  Шаг, который делают вторым, а надо первым — freshness:
    последняя дата в листинге : {freshness[0]}
    отставание от сегодня     : {freshness[1]} дн.
    строк                     : {thousands(freshness[2])}

  Если отставание больше допустимого — дальше идти незачем,
  какой бы красивой витрина ни получилась.""")

    # Зерно джойна — день-город, а НЕ заказ. Если джойнить погоду
    # прямо на строки заказов, sum(precipitation) умножится на число
    # заказов за день: сумма вырастет в сотни раз, и ни один тест
    # этого не поймает — запрос отработает штатно.
    rows = con.execute("""
        WITH daily AS (
            SELECT city, order_date,
                   count(*) AS orders, sum(amount) AS revenue
            FROM fct_orders
            WHERE partner_account = 'ACME_RETAIL'
            GROUP BY 1, 2
        )
        SELECT
            d.city,
            sum(d.orders)                             AS orders,
            round(sum(d.revenue), 0)                  AS revenue,
            round(avg(w.avg_temperature_air_2m_f), 1) AS avg_temp_f,
            round(sum(w.tot_precipitation_in), 1)     AS precip_in,
            round(100.0 * count(w.city_name) / count(*), 1) AS pct_days_matched
        FROM daily d
        LEFT JOIN weather_source.history_day w
               ON d.city = w.city_name
              AND d.order_date = w.date_valid_std
        GROUP BY 1 ORDER BY revenue DESC
    """).fetchall()

    print("\n  Джойн своих заказов с чужой погодой:\n")
    print(f"  {'city':<12}{'orders':>10}{'revenue':>14}{'temp_f':>9}"
          f"{'precip':>9}{'days%':>9}")
    print("  " + "-" * 63)
    for c, o, r, t, pr, m in rows:
        print(f"  {c:<12}{thousands(o):>10}{thousands(int(r)):>14}"
              f"{t:>9}{pr:>9}{m:>9}")

    print("""
  Обрати внимание на CTE daily: погода джойнится на день-город,
  а не на строку заказа. Наивный вариант — LEFT JOIN прямо на
  fct_orders — молча умножает sum(precipitation) на число заказов
  за день. Запрос отработает, тесты пройдут, цифра будет завышена
  в сотни раз. Правило: перед джойном справочника проверь, что
  зерно левой стороны совпадает с зерном справочника.

  pct_days_matched — вторая проверка, которую пропускают. LEFT JOIN
  не падает, он молча отдаёт NULL, и витрина показывает «выручка
  есть, погоды нет» без единой ошибки. Процент склейки должен
  быть метрикой, а не догадкой: в dbt это not_null-тест на
  ключе после джойна, а не взгляд на глазок.

  Здесь он меньше 100 по понятной причине: заказы есть за те
  дни, которых в листинге ещё нет — листинг отстаёт на сутки.
  Ровно та ситуация, ради которой проверка и заводится.

  И правило из скрипта 21, повторю: marketplace-таблица цепляется
  только через staging-слой. Вендор меняет схему когда захочет,
  и ты хочешь чинить один stg_-файл, а не двадцать витрин.""")
    return rows, subscribe_ms, freshness


# ═══════════════════════════════════════════════════════════
#  STEP 7 — контракт: потребитель не пишет
# ═══════════════════════════════════════════════════════════

def step7_readonly_contract(con):
    banner("STEP 7", "Контракт share: читать можно, писать нельзя")

    attempts = [
        ("INSERT через share",
         "INSERT INTO consumer_acct.v_partner_orders "
         "VALUES (-1, DATE '2026-01-01', 1.0, 'Osh', 'x')"),
        ("UPDATE через share",
         "UPDATE consumer_acct.v_partner_orders SET amount = 0 WHERE order_id = 1"),
        ("DELETE через share",
         "DELETE FROM consumer_acct.v_partner_orders WHERE order_id = 1"),
        ("INSERT в листинг",
         "INSERT INTO weather_source.history_day VALUES ('Osh', DATE '2026-01-01', 0, 0)"),
        ("CREATE TABLE в листинге",
         "CREATE TABLE weather_source.my_own_table (x INT)"),
    ]

    rows = []
    for name, sql in attempts:
        try:
            con.execute(sql)
            outcome = "ПРОШЛО — это дыра"
        except Exception as e:
            outcome = type(e).__name__
        rows.append((name, outcome))
        print(f"  {name:<26}→ {outcome}")

    print("""
  Пять из пяти отбиты, но отбиты РАЗНЫМИ механизмами, и это надо
  различать. Первые три упираются в то, что share отдан вьюхой:
  писать во вьюху нельзя. Последние две — в READ_ONLY подключение
  к чужому файлу.

  В Snowflake обоих механизмов нет: там shared-база read-only
  по самой модели share, и обойти это нельзя даже под
  ACCOUNTADMIN консьюмера. Результат совпал, причина другая —
  локальная симуляция показывает следствие, а не устройство.

  Практическое следствие для AE: если партнёр просит «дайте нам
  возможность дописывать свои корректировки» — share не подходит,
  нужен отдельный писчий канал (stage + его собственная таблица),
  а share остаётся только на чтение эталона.""")
    return rows


# ═══════════════════════════════════════════════════════════
#  STEP 8 — отчёты
# ═══════════════════════════════════════════════════════════

def step8_reports(share_meta, isolation, leaked, copy_vs, ro_rows, market_rows):
    banner("STEP 8", "CSV в reports/")

    artifacts = []
    grant_ms, grant_kb = share_meta

    artifacts.append(write_csv(
        REPORTS_DIR / "day99_100_copy_vs_share.csv",
        ["metric", "copy", "share", "unit"],
        [
            ["creation_time", f"{copy_vs['copy_s']:.3f}", f"{copy_vs['share_s']:.4f}", "s"],
            ["consumer_storage", f"{copy_vs['copy_mb']:.2f}", f"{copy_vs['share_mb']:.2f}", "MB"],
            ["rows_visible_before", copy_vs["copy_before"], copy_vs["share_before"], "rows"],
            ["rows_visible_after_insert", copy_vs["copy_after"], copy_vs["share_after"], "rows"],
            ["staleness_after_insert", copy_vs["share_after"] - copy_vs["copy_after"], 0, "rows"],
            ["share_grant_time", "", f"{grant_ms:.1f}", "ms"],
            ["share_metadata_growth", "", f"{grant_kb:.0f}", "KB"],
        ]))

    artifacts.append(write_csv(
        REPORTS_DIR / "day99_100_secure_view_isolation.csv",
        ["consumer_account", "rows_visible", "rows_owned", "verdict", "foreign_rows_leaked"],
        [[p, s, o, m, leaked if p == PARTNERS[0] else ""] for p, s, o, m in isolation]))

    artifacts.append(write_csv(
        REPORTS_DIR / "day99_100_readonly_contract.csv",
        ["statement", "outcome"], ro_rows))

    artifacts.append(write_csv(
        REPORTS_DIR / "day99_100_marketplace_join.csv",
        ["city", "orders", "revenue", "avg_temp_f", "precip_in", "pct_days_matched"],
        market_rows))

    return artifacts


# ═══════════════════════════════════════════════════════════
#  STEP 9 — на собеседовании
# ═══════════════════════════════════════════════════════════

def step9_interview():
    banner("STEP 9", "На собеседовании")
    print("""
  «Объясни Secure Data Sharing. Почему это дешевле, чем выгрузка?»

    Share — объект метаданных с грантами, не копия. Consumer
    читает micro-partitions producer'а напрямую; producer платит
    за storage одной копии независимо от числа потребителей,
    consumer платит за свой warehouse. Дешевле не потому, что
    «быстрее копируется», а потому что копирования нет вообще:
    нет второго storage, нет пайплайна, нет лага и нет расхождения
    между копиями. Десятый потребитель стоит одну строку в каталоге.

  «Почему в share нельзя положить обычную вьюху?»

    Обычная вьюха раскрывает своё определение консьюмеру и
    допускает проталкивание предикатов до фильтра доступа —
    через это данные утекают косвенно, например текстом ошибки
    на чужих значениях. SECURE VIEW прячет определение и
    отключает такие оптимизации. Платим производительностью,
    покупаем то, что фильтр доступа применяется первым.

  «Как одним объектом отдать каждому партнёру только его строки?»

    Secure view с WHERE partner_account = CURRENT_ACCOUNT().
    Внутри shared secure view эта функция возвращает аккаунт
    потребителя. Вариант с маппинг-таблицей — когда соответствие
    сложнее один-к-одному; саму маппинг-таблицу в share не кладут.
    Проверяется тестом «сколько ЧУЖИХ строк видно», а не
    «сколько своих» — утечка выглядит как лишние строки.

  «Клиент не на Snowflake. Варианты?»

    Reader account: producer создаёт аккаунт и платит за весь его
    compute — поэтому resource monitor настраивается ДО выдачи
    кредов, иначе чужой тяжёлый запрос приходит твоим счётом.
    Если клиенту нужен не интерактивный SQL, а файл раз в сутки —
    share вообще лишний, дешевле COPY INTO в его S3.

  «Чем Marketplace отличается от share технически?»

    Ничем — под капотом тот же Secure Data Sharing. Marketplace
    это витрина поверх: описание, sample-запросы, версии,
    биллинг через Snowflake. Private listing — тот же механизм
    для названных аккаунтов; на практике это лучший способ
    шарить данные между аккаунтами одной компании.

  «Подключил датасет с Marketplace. Что сделаешь до витрины?»

    Две проверки. Freshness: max(date) и отставание — листинг
    может обновляться раз в квартал, и это выясняется до, а не
    после. И процент склейки после джойна — LEFT JOIN не падает,
    он молча отдаёт NULL. Обе проверки оформляются как source
    freshness и not_null-тест в dbt. Ссылаться из mart-модели
    напрямую на marketplace-таблицу нельзя: вендор меняет схему
    без предупреждения, между ним и витринами должен стоять
    staging-слой.

  «Что ломается, если producer добавил колонку?»

    У консьюмера она появляется сразу — DDL тоже не копируется.
    Молча съезжает SELECT *, ломаются контракты. Поэтому в share
    кладут вьюху, а не таблицу: вьюха и есть контракт, который
    producer меняет осознанно.""")


def main():
    print(SEP)
    print("  lesson99_100.py — Days 99-100: Data Sharing + Marketplace")
    print(SEP)

    step1_snowflake_sql()

    for p in (PRODUCER_DB, CONSUMER_DB, COPY_DB, MARKET_DB):
        if p.exists():
            p.unlink()

    con = duckdb.connect(str(PRODUCER_DB))
    try:
        con.execute("SET preserve_insertion_order = false")
        step2_build_producer(con)
        share_meta = step3_share_catalog(con)
        isolation, leaked = step4_secure_view(con)
        copy_vs = step5_copy_vs_share(con)
        market_rows, _, _ = step6_marketplace(con)
        ro_rows = step7_readonly_contract(con)
    finally:
        con.close()

    artifacts = step8_reports(share_meta, isolation, leaked,
                              copy_vs, ro_rows, market_rows)
    step9_interview()

    print("\n" + SEP)
    print("  ALL DONE")
    print(SEP)
    print("""
Артефакты:
  snowflake_setup/19_secure_data_sharing.sql
  snowflake_setup/20_reader_account.sql
  snowflake_setup/21_marketplace.sql
""" + "".join(f"  {p.relative_to(PROJECT_ROOT)}\n" for p in artifacts) + """
Что осталось несделанным честно:
  Snowflake-аккаунта нет — скрипты 19-21 написаны, но не выполнялись.
  Главного свойства share локально не показать: consumer платит за
  свой warehouse, producer только за storage. Здесь нет ни двух
  аккаунтов, ни разделения storage/compute, ни биллинга — показано
  только следствие: копирования нет, лага нет.
  Reader Account не симулируется вообще: это провижининг аккаунта
  на стороне Snowflake.
  Marketplace-листинг заменён локальным файлом — подписка на реальный
  листинг делается в UI.
  READ_ONLY в DuckDB — свойство подключения; в Snowflake запрет на
  запись прошит в модель share. Эффект совпал, механизм разный.

Next steps:
  1. Неделя 13 закрыта. Дальше Days 101-104 — Medallion Architecture
  2. При появлении аккаунта: 19 -> 21 в Worksheet, для 20 нужен
     второй аккаунт или managed account
  3. Концепты в базу: /ae-concept Secure Data Sharing,
     /ae-concept Secure View, /ae-concept Reader Account,
     /ae-concept Snowflake Marketplace

Git:
  git add lesson99_100.py snowflake_setup/{19,20,21}_*.sql reports/day99_100_*
  git commit -m "feat: Days 99-100 Data Sharing + Marketplace"
""")


if __name__ == "__main__":
    main()
