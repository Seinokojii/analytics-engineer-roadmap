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
