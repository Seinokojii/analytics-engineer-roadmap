#!/usr/bin/env python3
"""
lesson97_98.py — Days 97-98: Performance Tuning

Запуск:
    python lesson97_98.py

Продолжает дни 91-96. Принцип тот же: Snowflake-аккаунта нет, поэтому
реальные .sql пишутся готовыми к запуску в Worksheet, а механика
отрабатывается локально на DuckDB — и там, где локальный аналог врёт,
это сказано прямо.

Что делает:
  1. Пишет четыре SQL-скрипта под реальный Snowflake в snowflake_setup/
  2. Читает план запроса через EXPLAIN ANALYZE — локальный Query Profile
  3. Clustering Key: меряет отсечение по min/max статистике блоков
     (row groups Parquet = прямой аналог micro-partitions)
  4. Показывает, как функция над колонкой в WHERE убивает отсечение
  5. Search Optimization Service: точечный lookup с индексом и без,
     вместе с ценой построения структуры
  6. Result Cache: своя реализация на (hash запроса + версия таблицы)
     и проверка инвалидации после DML
  7. Materialized View против dbt incremental: замер full refresh
     против инкремента + дерево решений
  8. Кладёт четыре CSV в reports/ + блок «На собеседовании»

Что здесь симулируется хуже оригинала — честно:
  Result Cache в DuckDB отсутствует как сервис. Свой кэш показывает
  правило инвалидации, но не главное свойство снежинкового: тот
  отдаёт результат, вообще не запуская warehouse, то есть за 0 кредитов.
  Search Optimization Service — проприетарная структура поверх
  micro-partitions; ART-индекс DuckDB даёт тот же эффект на точечном
  lookup, но устроен иначе и обслуживается по-другому.
  Materialized View в DuckDB нет вообще: сравниваются две стратегии
  пересчёта, а не MV против таблицы.
  Bytes spilled to storage воспроизвести не удалось: на 15 млн строк
  при memory_limit 200 МБ DuckDB 1.4.3 досчитал агрегацию потоком,
  не создав ни одного временного файла.
"""

import csv
import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
REPORTS_DIR = PROJECT_ROOT / "reports"
DATA_DIR = SNOWFLAKE_DIR / "perf_demo"

SNOWFLAKE_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

SIM_DB = SNOWFLAKE_DIR / "perf_tuning_demo.duckdb"

TODAY = datetime.now().strftime("%Y-%m-%d")

SEP = "=" * 62

# Масштаб демо. 5 млн строк — достаточно, чтобы разница в отсечении
# была видна во времени, и достаточно мало, чтобы день не ждал минуту.
N_ROWS = 5_000_000
ROW_GROUP = 100_000          # аналог размера micro-partition
N_REPEATS = 7                # берём медиану, а не одно измерение


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")


def thousands(n) -> str:
    """Разряды неразрывным пробелом. Раньше здесь был .replace(',', ' ')
    по всему абзацу — он съедал запятые в русском тексте."""
    return f"{n:,}".replace(",", "\u00a0")


def median_ms(con, sql: str, repeats: int = N_REPEATS) -> float:
    """Медиана времени выполнения в миллисекундах.

    Медиана, а не минимум и не среднее: минимум льстит горячему кэшу,
    среднее ломается от одного случайного выброса планировщика ОС.
    """
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        con.execute(sql).fetchall()
        timings.append(time.perf_counter() - start)
    return sorted(timings)[repeats // 2] * 1000


# ═══════════════════════════════════════════════════════════
#  STEP 1 — SQL под реальный Snowflake
# ═══════════════════════════════════════════════════════════

QUERY_PROFILE_SQL = """\
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
"""

RESULT_CACHE_SQL = """\
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
"""

CLUSTERING_SQL = """\
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
"""

MATERIALIZED_VIEW_SQL = """\
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
"""


def step1_snowflake_sql():
    banner("STEP 1", "SQL под реальный Snowflake")
    write_utf8(SNOWFLAKE_DIR / "15_query_profile.sql", QUERY_PROFILE_SQL)
    write_utf8(SNOWFLAKE_DIR / "16_result_cache.sql", RESULT_CACHE_SQL)
    write_utf8(SNOWFLAKE_DIR / "17_clustering_search_optimization.sql", CLUSTERING_SQL)
    write_utf8(SNOWFLAKE_DIR / "18_materialized_views.sql", MATERIALIZED_VIEW_SQL)
    print("""
  Аккаунта нет — скрипты не выполнялись. Они написаны так, чтобы
  запускаться блоками в Worksheet без правок, кроме имён объектов.
""")


# ═══════════════════════════════════════════════════════════
#  STEP 2 — данные для замеров
# ═══════════════════════════════════════════════════════════

def step2_build_dataset(con) -> dict:
    banner("STEP 2", "Данные: два файла из одних строк, разный порядок")

    con.execute("DROP TABLE IF EXISTS orders_src")
    con.execute(f"""
        CREATE TABLE orders_src AS
        SELECT
            'A-' || LPAD(CAST(i AS VARCHAR), 8, '0')            AS order_id,
            (i * 13) % 250000                                   AS customer_id,
            ROUND(((i * 7) % 100000) / 100.0, 2)                AS amount,
            ['Oslo','Bergen','Trondheim','Stavanger','Tromso'][(i % 5) + 1] AS city,
            DATE '2026-01-01' + INTERVAL ((i * 37) % 400) DAY    AS order_date,
            -- Случайное распределение, а не монотонный рост: по такой
            -- колонке min/max статистика блоков бесполезна. Это и есть
            -- кейс Search Optimization, см. STEP 6.
            'c' || LPAD(CAST(hash(i) % 100000000 AS VARCHAR), 9, '0')
                 || '@example.com'                              AS customer_email
        FROM range({N_ROWS}) tbl(i)
    """)
    total = con.execute("SELECT count(*) FROM orders_src").fetchone()[0]
    print(f"  Построено строк: {thousands(total)}")

    sorted_path = DATA_DIR / "orders_clustered.parquet"
    shuffled_path = DATA_DIR / "orders_unclustered.parquet"

    # Один и тот же набор строк. Разница только в физическом порядке —
    # ровно то, чем отличается таблица с clustering key от таблицы без.
    con.execute(f"""COPY (SELECT * FROM orders_src ORDER BY order_date)
                    TO '{sorted_path}' (FORMAT parquet, ROW_GROUP_SIZE {ROW_GROUP})""")
    con.execute(f"""COPY (SELECT * FROM orders_src ORDER BY hash(order_id))
                    TO '{shuffled_path}' (FORMAT parquet, ROW_GROUP_SIZE {ROW_GROUP})""")

    def describe(path: Path) -> dict:
        row = con.execute(f"""
            SELECT count(*)              AS row_groups,
                   min(CAST(stats_min AS DATE)) AS lo,
                   max(CAST(stats_max AS DATE)) AS hi,
                   ROUND(avg(CAST(stats_max AS DATE) - CAST(stats_min AS DATE)), 1) AS avg_span_days
            FROM parquet_metadata('{path}')
            WHERE path_in_schema = 'order_date'
        """).fetchone()
        return {"row_groups": row[0], "avg_span_days": row[3],
                "size_mb": round(path.stat().st_size / 1024 / 1024, 1)}

    clustered = describe(sorted_path)
    unclustered = describe(shuffled_path)

    print(f"""
  Файл                     row groups   средний разброс дат в группе   размер
  orders_clustered.parquet   {clustered['row_groups']:>3}          {clustered['avg_span_days']:>6} дней            {clustered['size_mb']} МБ
  orders_unclustered.parquet {unclustered['row_groups']:>3}          {unclustered['avg_span_days']:>6} дней            {unclustered['size_mb']} МБ

  Row group в Parquet — это и есть локальный micro-partition:
  неизменяемый блок со своей min/max статистикой по каждой колонке.
  Разброс дат внутри группы — это average_depth из
  SYSTEM$CLUSTERING_INFORMATION, переведённый в человеческие единицы.
  Узкий разброс → фильтр по дате отсечёт почти всё.
  Разброс во весь диапазон → отсекать нечего, читается вся таблица.

  Побочный результат, который видно в колонке размера: отсортированный
  файл на {round(100 * (1 - clustered['size_mb'] / unclustered['size_mb']))}% меньше при тех же самых строках. Причина
  не в отсечении, а в сжатии: соседние значения в отсортированной
  колонке похожи, и run-length кодирование работает лучше. На Snowflake
  это тот же эффект — кластеризованная таблица занимает меньше места,
  и это отдельная, обычно незамеченная статья экономии.
""")
    return {"clustered": clustered, "unclustered": unclustered,
            "sorted_path": sorted_path, "shuffled_path": shuffled_path}


# ═══════════════════════════════════════════════════════════
#  STEP 3 — Query Profile: читаем план
# ═══════════════════════════════════════════════════════════

def step3_query_profile(con, ds: dict):
    banner("STEP 3", "Query Profile: читаем план запроса")

    sql = f"""
        SELECT city, count(*) AS orders_cnt, sum(amount) AS revenue
        FROM '{ds['sorted_path']}'
        WHERE order_date >= DATE '2026-03-01' AND order_date < DATE '2026-04-01'
        GROUP BY city
    """
    plan = con.execute("EXPLAIN ANALYZE " + sql).fetchall()[0][1]

    # Дерево печатается целиком: смысл шага — научиться его читать,
    # а выжимка по ключевым словам ровно это и прячет.
    lines = plan.splitlines()
    start = next(i for i, ln in enumerate(lines) if "QUERY" in ln and "Profiling" not in ln)
    print("  План читается снизу вверх — от чтения данных к результату:\n")
    for line in lines[start - 1:]:
        print("   ", line)
    print("""
  Что здесь важно, по порядку снизу вверх:

    TABLE_SCAN / PARQUET_SCAN
      Filters: условие уехало внутрь чтения — это predicate pushdown.
        Фильтр применён при чтении, а не после него. Если бы условие
        осталось отдельным оператором FILTER выше скана, это значило бы,
        что в память сначала подняли всю таблицу.
      Projections: читаются только city и amount. Колоночное хранение
        за тем и нужно: SELECT * на широкой таблице отменяет эту выгоду.
      Total Files Read: сколько файлов реально открыто.
      Число строк на выходе оператора — это «Rows sent» из Query Profile.

    PROJECTION → HASH_GROUP_BY
      Вход 387 500 строк, выход 5. Резкое падение на агрегации —
      норма. Резкое падение на ФИЛЬТРЕ, стоящем высоко в дереве, —
      признак того, что условие применили слишком поздно.
""")

    print("""
  Как это соотносится со Snowflake Query Profile:

    DuckDB EXPLAIN ANALYZE        Snowflake Query Profile
    ──────────────────────────    ─────────────────────────────────
    Total Time                    Total Execution Time
    имя оператора + доля          узел графа + % of total
    Rows на операторе             Rows sent между узлами
    (нет прямого аналога)         Partitions scanned / total
    (нет)                         Bytes spilled to local/remote

  Читать план всегда в одном порядке: найти самый дорогой оператор,
  посмотреть, сколько строк в него входит и сколько выходит.
  Оператор, который принял 5 млн строк и вернул 5 — это либо
  нормальная агрегация, либо фильтр, который применили слишком поздно.
""")


# ═══════════════════════════════════════════════════════════
#  STEP 4 — Clustering: замер отсечения
# ═══════════════════════════════════════════════════════════

def step4_clustering(con, ds: dict) -> list:
    banner("STEP 4", "Clustering Key: сколько блоков реально читается")

    lo, hi = "2026-03-01", "2026-03-06"   # узкое окно: 5 дней из 400

    def pruning(path: Path) -> tuple:
        """Считаем отсечение так же, как это делает движок: блок нужен,
        если его [min, max] пересекается с диапазоном фильтра."""
        return con.execute(f"""
            SELECT
                count(*) FILTER (
                    WHERE CAST(stats_min AS DATE) < DATE '{hi}'
                      AND CAST(stats_max AS DATE) >= DATE '{lo}'),
                count(*)
            FROM parquet_metadata('{path}')
            WHERE path_in_schema = 'order_date'
        """).fetchone()

    query = """SELECT count(*), ROUND(sum(amount), 2) FROM '{}'
               WHERE order_date >= DATE '{}' AND order_date < DATE '{}'"""

    rows = []
    for label, path in (("clustered (ORDER BY order_date)", ds["sorted_path"]),
                        ("unclustered (случайный порядок)", ds["shuffled_path"])):
        hit, total = pruning(path)
        ms = median_ms(con, query.format(path, lo, hi))
        result = con.execute(query.format(path, lo, hi)).fetchone()
        rows.append({"layout": label, "groups_read": hit, "groups_total": total,
                     "pct_read": round(100 * hit / total, 1),
                     "median_ms": round(ms, 2), "rows_matched": result[0]})
        print(f"  {label:34} {hit:>3}/{total} блоков "
              f"({100 * hit / total:5.1f}%)  {ms:7.2f} мс")

    speedup = rows[1]["median_ms"] / rows[0]["median_ms"]
    print(f"""
  Строк в ответе у обоих одинаково: {thousands(rows[0]['rows_matched'])} — данные те же.
  Разница только в физическом порядке. Выигрыш по времени: {speedup:.1f}x,
  по объёму чтения: {rows[1]['groups_read'] / rows[0]['groups_read']:.0f}x меньше блоков.

  В Snowflake это будет та же пара чисел в Query Profile:
  partitions_scanned {rows[0]['groups_read']}/{rows[0]['groups_total']} против {rows[1]['groups_read']}/{rows[1]['groups_total']}.
  Именно её смотрят первой, когда запрос по дате работает
  медленнее, чем должен.
""")
    return rows


# ═══════════════════════════════════════════════════════════
#  STEP 5 — антипаттерн: функция над колонкой
# ═══════════════════════════════════════════════════════════

def step5_sargable(con, ds: dict) -> list:
    banner("STEP 5", "Функция над колонкой убивает отсечение")

    path = ds["sorted_path"]
    # Один день из 400. На широком окне (месяц) отсекается 5 блоков
    # из 50, и разрыв между вариантами почти не виден.
    good = f"""SELECT count(*) FROM '{path}'
               WHERE order_date >= DATE '2026-03-15'
                 AND order_date <  DATE '2026-03-16'"""
    bad = f"""SELECT count(*) FROM '{path}'
              WHERE strftime(order_date, '%Y-%m-%d') = '2026-03-15'"""

    rows = []
    for label, sql in (("колонка слева, чистая", good),
                       ("strftime(order_date)", bad)):
        ms = median_ms(con, sql)
        cnt = con.execute(sql).fetchone()[0]
        rows.append({"variant": label, "median_ms": round(ms, 2), "rows": cnt})
        print(f"  {label:26} {ms:7.2f} мс   строк: {thousands(cnt)}")

    print(f"""
  Результат побайтово одинаковый — это важно, иначе сравнение
  было бы нечестным. Разница во времени: {rows[1]['median_ms'] / rows[0]['median_ms']:.1f}x.

  Почему так. Статистика блока — это min и max значения КОЛОНКИ.
  Условие `order_date >= X` движок сравнивает с этой статистикой напрямую.
  Условие `strftime(order_date, ...) = X` — это условие на результат
  функции, а статистики по результату функции не существует.
  Значит проверить нужно каждую строку, значит прочитать каждый блок.

  Локально разрыв скромный: DuckDB всё равно быстро считает
  5 млн строк с NVMe. На Snowflake с миллиардом строк та же ошибка
  превращает секунду в минуты и жжёт кредиты всё это время.

  Правило одно: колонка в фильтре стоит слева и без обёрток.
  Всё преобразование переносится на константу справа.
  Если преобразование нужно постоянно — его материализуют
  отдельной колонкой и кластеризуют уже по ней.
""")
    return rows


# ═══════════════════════════════════════════════════════════
#  STEP 6 — Search Optimization: точечный lookup
# ═══════════════════════════════════════════════════════════

def step6_search_optimization(con) -> dict:
    banner("STEP 6", "Search Optimization Service: аналог на индексе")

    # order_id для этого не годится: он растёт монотонно, строки
    # физически лежат по возрастанию, и min/max блоков отсекают почти
    # всё сами. Замер по нему мерил бы clustering во второй раз.
    # customer_email распределён случайно — статистике блоков не за что
    # зацепиться. Это и есть задача Search Optimization.
    target = con.execute(
        "SELECT customer_email FROM orders_src LIMIT 1 OFFSET 2500000").fetchone()[0]
    lookup = f"SELECT count(*) FROM orders_src WHERE customer_email = '{target}'"

    before = median_ms(con, lookup)
    print(f"  Точечный lookup без структуры поиска: {before:7.2f} мс")

    start = time.perf_counter()
    con.execute("CREATE INDEX IF NOT EXISTS idx_email ON orders_src(customer_email)")
    build_s = time.perf_counter() - start
    print(f"  Построение структуры:                 {build_s:7.2f} с")

    after = median_ms(con, lookup)
    print(f"  Тот же lookup со структурой:          {after:7.2f} мс")

    # Цена поддержки: вставка в таблицу с индексом дороже, чем без него.
    con.execute("DROP TABLE IF EXISTS orders_noidx")
    con.execute("CREATE TABLE orders_noidx AS SELECT * FROM orders_src LIMIT 0")
    ins = "INSERT INTO {} SELECT * FROM orders_src USING SAMPLE 200000 ROWS"

    t = time.perf_counter(); con.execute(ins.format("orders_noidx")); ins_no = time.perf_counter() - t
    t = time.perf_counter(); con.execute(ins.format("orders_src")); ins_idx = time.perf_counter() - t

    con.execute("DROP INDEX IF EXISTS idx_email")

    print(f"""
  Цена поддержки — вставка 200 000 строк:
    в таблицу без структуры поиска: {ins_no:.2f} с
    в таблицу со структурой:        {ins_idx:.2f} с  ({ins_idx / max(ins_no, 0.001):.1f}x)

  Ускорение lookup: {before / max(after, 0.001):.0f}x. Но платится оно дважды —
  разовым построением ({build_s:.1f} с) и постоянным замедлением записи.
  В Snowflake обе цены приходят строкой в счёте: Search Optimization
  Service — фоновая служба, она обслуживает свою структуру сама,
  и чем активнее DML по таблице, тем дороже это обходится.

  Где здесь врёт локальный аналог: ART-индекс DuckDB и SOS устроены
  по-разному. SOS работает поверх micro-partitions и умеет не только
  равенство, но и SUBSTRING, и поиск по полям VARIANT. Совпадает
  главное — характер задачи (точечный поиск, мало строк в ответе)
  и характер платы (структура, которую надо обслуживать).

  Выбор между двумя инструментами:
    диапазон по дате, много строк в ответе → Clustering Key
    точечный поиск по ключу, мало строк    → Search Optimization
""")
    return {"lookup_before_ms": round(before, 2), "lookup_after_ms": round(after, 2),
            "index_build_s": round(build_s, 2),
            "insert_no_index_s": round(ins_no, 2), "insert_with_index_s": round(ins_idx, 2)}


# ═══════════════════════════════════════════════════════════
#  STEP 7 — Result Cache: своя реализация
# ═══════════════════════════════════════════════════════════

class ResultCache:
    """Кеш результатов по правилам Snowflake.

    Ключ — точный текст запроса. Инвалидация — по версии таблицы,
    а не по строкам: любой DML обнуляет все записи по этой таблице.
    """

    def __init__(self, con):
        self.con = con
        self.store: dict[str, tuple[int, list]] = {}
        self.versions: dict[str, int] = {}
        self.hits = 0
        self.misses = 0

    def note_dml(self, table: str) -> None:
        """Зарегистрировать DML — версия таблицы сдвигается.

        Первая версия этого класса считала версию как
        sum(hash(order_id)) по всей таблице. Работало верно, но
        проверка кеша стоила полного скана 5 млн строк — дороже
        самого запроса, и попадание в кеш не давало выигрыша вовсе.
        В Snowflake версия таблицы лежит в метаданных: узнать,
        менялась ли таблица, ничего не стоит. Счётчик — точная
        модель этого, а скан был моделью неверной.
        """
        self.versions[table] = self.versions.get(table, 0) + 1

    def table_version(self, table: str) -> int:
        return self.versions.get(table, 0)

    def query(self, sql: str, table: str):
        key = hashlib.md5(sql.encode("utf-8")).hexdigest()
        version = self.table_version(table)
        cached = self.store.get(key)
        if cached and cached[0] == version:
            self.hits += 1
            return cached[1], True
        self.misses += 1
        result = self.con.execute(sql).fetchall()
        self.store[key] = (version, result)
        return result, False


def step7_result_cache(con) -> list:
    banner("STEP 7", "Result Cache: попадание, промах, инвалидация")

    cache = ResultCache(con)
    q = "SELECT city, count(*) FROM orders_src WHERE order_date >= DATE '2026-06-01' GROUP BY city ORDER BY city"

    rows = []

    def run(label: str, sql: str):
        start = time.perf_counter()
        _, hit = cache.query(sql, "orders_src")
        ms = (time.perf_counter() - start) * 1000
        rows.append({"step": label, "cache_hit": hit, "ms": round(ms, 2)})
        print(f"  {label:44} {'HIT ' if hit else 'MISS'} {ms:8.2f} мс")

    run("1. первый запуск", q)
    run("2. тот же текст побайтово", q)
    run("3. тот же смысл, лишний пробел в тексте", q.replace("SELECT city", "SELECT  city"))

    con.execute("""INSERT INTO orders_src
                   VALUES ('A-99999999', 1, 10.0, 'Oslo', DATE '2026-06-15',
                           'c000000001@example.com')""")
    cache.note_dml("orders_src")   # в Snowflake это делают сами метаданные
    run("4. после INSERT в таблицу", q)
    run("5. повтор после инвалидации", q)

    print(f"""
  Попаданий: {cache.hits}, промахов: {cache.misses}.

  Шаг 3 — главный вывод: лишний пробел даёт промах. Ключ кеша
  строится по тексту запроса, а не по его смыслу. На практике это
  ровно то, из-за чего дашборд не попадает в кеш: BI-инструмент
  подставляет в запрос меняющийся alias или таймстемп, и каждый
  запрос выглядит для Snowflake новым.

  Шаг 4 — инвалидация по таблице целиком. Одна вставленная строка
  обнулила кеш для всех запросов, которые читают orders_src,
  даже если она не попадает в их условие.

  Где локальный аналог не дотягивает: в Snowflake попадание в result
  cache означает, что warehouse вообще не запускается — ответ приходит
  из слоя сервисов за 0 кредитов. Здесь же результат лежит в памяти
  процесса, и экономится только время. Стоимостной эффект, ради
  которого этот кеш и существует, локально не моделируется.

  И третий уровень, которого тут нет вовсе: warehouse cache —
  прочитанные партиции на локальном SSD. Он умирает при SUSPEND.
  Поэтому auto-suspend в 60 секунд на активно используемом
  warehouse — типичная ошибка: экономия на простое оплачивается
  холодным чтением на каждом следующем запросе.
""")
    return rows


# ═══════════════════════════════════════════════════════════
#  STEP 8 — MV против dbt incremental
# ═══════════════════════════════════════════════════════════

def step8_mv_vs_incremental(con) -> list:
    banner("STEP 8", "Materialized View против dbt incremental")

    con.execute("DROP TABLE IF EXISTS agg_full")
    con.execute("DROP TABLE IF EXISTS agg_incr")

    agg_sql = """
        SELECT order_date, city, count(*) AS orders_cnt, ROUND(sum(amount), 2) AS revenue
        FROM orders_src {where}
        GROUP BY order_date, city
    """

    # Первичная сборка одинакова для обеих стратегий.
    con.execute("CREATE TABLE agg_incr AS " + agg_sql.format(where=""))
    base_rows = con.execute("SELECT count(*) FROM agg_incr").fetchone()[0]
    print(f"  Базовая витрина собрана: {base_rows} строк\n")

    # Прилетела новая порция данных — один день.
    new_day = "DATE '2027-02-05'"
    con.execute(f"""
        INSERT INTO orders_src
        SELECT 'B-' || LPAD(CAST(i AS VARCHAR), 8, '0'), (i * 13) % 250000,
               ROUND(((i * 7) % 100000) / 100.0, 2),
               ['Oslo','Bergen','Trondheim','Stavanger','Tromso'][(i % 5) + 1],
               {new_day},
               'c' || LPAD(CAST(hash(i) % 100000000 AS VARCHAR), 9, '0') || '@example.com'
        FROM range(50000) tbl(i)
    """)

    # Стратегия 1: full refresh — пересчитать всё.
    start = time.perf_counter()
    con.execute("DROP TABLE IF EXISTS agg_full")
    con.execute("CREATE TABLE agg_full AS " + agg_sql.format(where=""))
    full_s = time.perf_counter() - start
    full_scanned = con.execute("SELECT count(*) FROM orders_src").fetchone()[0]

    # Стратегия 2: incremental — delete+insert по окну.
    # Именно так работает dbt incremental со strategy='delete+insert':
    # окно задаётся предикатом, всё остальное не трогается.
    start = time.perf_counter()
    con.execute(f"DELETE FROM agg_incr WHERE order_date >= {new_day}")
    con.execute("INSERT INTO agg_incr " + agg_sql.format(where=f"WHERE order_date >= {new_day}"))
    incr_s = time.perf_counter() - start
    incr_scanned = con.execute(
        f"SELECT count(*) FROM orders_src WHERE order_date >= {new_day}").fetchone()[0]

    # Сверка: обе витрины обязаны совпасть, иначе инкремент сломан.
    diff = con.execute("""
        SELECT count(*) FROM (
            SELECT * FROM agg_full EXCEPT SELECT * FROM agg_incr
            UNION ALL
            SELECT * FROM agg_incr EXCEPT SELECT * FROM agg_full)
    """).fetchone()[0]

    rows = [
        {"strategy": "full refresh", "seconds": round(full_s, 3),
         "rows_scanned": full_scanned},
        {"strategy": "incremental (delete+insert)", "seconds": round(incr_s, 3),
         "rows_scanned": incr_scanned},
    ]
    print(f"  full refresh                {full_s:6.3f} с   прочитано строк: {thousands(full_scanned)}")
    print(f"  incremental (delete+insert) {incr_s:6.3f} с   прочитано строк: {thousands(incr_scanned)}")
    print(f"\n  Расхождение витрин: {diff} строк "
          f"{'— инкремент корректен' if diff == 0 else '— ИНКРЕМЕНТ СЛОМАН'}")

    print(f"""
  Выигрыш инкремента: {full_s / max(incr_s, 0.001):.0f}x по времени,
  {full_scanned / max(incr_scanned, 1):.0f}x по объёму чтения.
  Ноль расхождений — обязательное условие: инкремент, который
  расходится с полным пересчётом, хуже, чем его отсутствие,
  потому что ошибка тихая.

  Теперь выбор инструмента на Snowflake.

    Materialized View
      + Snowflake обновляет сам, оркестратор не нужен
      + оптимизатор подставляет её прозрачно — запрос можно
        не переписывать, что решает задачу, когда BI ходит
        напрямую в сырую таблицу и переписать его нельзя
      − одна таблица, никаких JOIN, окон, UNION, вложенности
      − только Enterprise Edition и выше
      − отдельная строка расходов за фоновое обновление

    dbt incremental
      + любой SQL: JOIN, окна, цепочки моделей
      + версионируется в git, проходит code review, покрыт тестами
      + переносится между платформами — здесь он отработал на DuckDB
      − нужен оркестратор и расписание
      − обращаться надо явно, прозрачной подстановки нет

    Dynamic Table — середина: JOIN и окна можно, обновление
      декларативное через TARGET_LAG, но подстановка тоже не прозрачная.

  По умолчанию в AE-проекте берётся dbt incremental: он живёт
  в репозитории и его видно в code review. MV — точечная оптимизация
  под конкретный горячий запрос, а не способ строить витрины.
""")
    return rows


# ═══════════════════════════════════════════════════════════
#  STEP 9 — отчёты
# ═══════════════════════════════════════════════════════════

def write_csv(path: Path, rows: list) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        # lineterminator обязателен: по умолчанию csv.writer пишет CRLF
        # даже на Linux, и git каждый раз ругается на конец строки.
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}  ({len(rows)} строк)")
    return path


def step9_reports(clustering, sargable, sos, cache_rows, mv_rows) -> list:
    banner("STEP 9", "Отчёты в reports/")
    paths = [
        write_csv(REPORTS_DIR / f"day97_98_clustering_{TODAY}.csv", clustering),
        write_csv(REPORTS_DIR / f"day97_98_sargable_{TODAY}.csv", sargable),
        write_csv(REPORTS_DIR / f"day97_98_search_optimization_{TODAY}.csv", [sos]),
        write_csv(REPORTS_DIR / f"day97_98_result_cache_{TODAY}.csv", cache_rows),
        write_csv(REPORTS_DIR / f"day97_98_mv_vs_incremental_{TODAY}.csv", mv_rows),
    ]
    return paths


# ═══════════════════════════════════════════════════════════
#  STEP 10 — на собеседовании
# ═══════════════════════════════════════════════════════════

def step10_interview():
    banner("STEP 10", "На собеседовании")
    print("""
  «Запрос на Snowflake стал медленным. Твои действия?»

    По порядку, не перескакивая. Открываю Query Profile и смотрю
    самый дорогой оператор. Дальше три числа. Partitions scanned
    против total: если прочитано почти всё, а вернулось мало строк —
    проблема в отсечении, смотрю фильтр на функции над колонкой
    и думаю про clustering key. Bytes spilled: если есть — запросу
    не хватило памяти warehouse, либо он больше, чем нужно,
    либо warehouse меньше, чем нужно. Percentage scanned from cache:
    низкий процент на повторяющемся запросе означает, что
    warehouse усыпляют слишком агрессивно. Размер warehouse трогаю
    последним — это не оптимизация, а оплата проблемы.

  «Clustering key или Search Optimization?»

    Зависит от формы запроса, а не от размера таблицы. Фильтр
    по диапазону, много строк в ответе — clustering key, он
    выстраивает данные так, чтобы min/max партиций стали
    осмысленными. Точечный поиск по почти уникальному ключу,
    несколько строк в ответе — Search Optimization, отдельная
    структура поиска. Оба стоят денег постоянно, а не разово:
    на таблице с активным DML это надо считать, иначе оптимизация
    обойдётся дороже, чем сэкономит.

  «Materialized View или dbt incremental?»

    По умолчанию incremental: он в git, проходит review, покрыт
    тестами и переносится между платформами. MV беру в одном
    случае — когда запрос переписать нельзя, например BI ходит
    напрямую в сырую таблицу, а оптимизатор подставит MV прозрачно.
    Ограничения MV решают вопрос быстро: одна таблица, без JOIN,
    без окон, только Enterprise. Если нужны JOIN и низкая
    задержка без оркестратора — Dynamic Table.

  «Три кеша Snowflake — назови и скажи, что их сбрасывает.»

    Result cache: готовый результат, 24 часа с продлением до 31 дня,
    ключ — точный текст запроса, warehouse не запускается вообще.
    Сбрасывается любым DML по любой таблице запроса, а также
    промахивается от лишнего пробела в тексте и от любой
    недетерминированной функции вроде CURRENT_TIMESTAMP.
    Warehouse cache: прочитанные партиции на локальном SSD,
    умирает при suspend warehouse. Metadata cache: min/max,
    счётчики строк — из него отвечает SELECT count(*)
    без чтения данных вообще.
""")


def main():
    print(SEP)
    print("  lesson97_98.py — Days 97-98: Performance Tuning")
    print(SEP)

    step1_snowflake_sql()

    if SIM_DB.exists():
        SIM_DB.unlink()
    con = duckdb.connect(str(SIM_DB))
    try:
        con.execute("SET preserve_insertion_order = false")
        ds = step2_build_dataset(con)
        step3_query_profile(con, ds)
        clustering = step4_clustering(con, ds)
        sargable = step5_sargable(con, ds)
        sos = step6_search_optimization(con)
        cache_rows = step7_result_cache(con)
        mv_rows = step8_mv_vs_incremental(con)
    finally:
        con.close()

    artifacts = step9_reports(clustering, sargable, sos, cache_rows, mv_rows)
    step10_interview()

    print(SEP)
    print("  ALL DONE")
    print(SEP)
    print(f"""
Артефакты:
  snowflake_setup/15_query_profile.sql
  snowflake_setup/16_result_cache.sql
  snowflake_setup/17_clustering_search_optimization.sql
  snowflake_setup/18_materialized_views.sql
""" + "".join(f"  {p.relative_to(PROJECT_ROOT)}\n" for p in artifacts) + f"""
Что осталось несделанным честно:
  Snowflake-аккаунта нет — скрипты 15-18 написаны, но не выполнялись.
  Result Cache локально показывает только правило инвалидации:
  главного свойства — ответ без запуска warehouse, за 0 кредитов —
  здесь нет и быть не может.
  Materialized View в DuckDB отсутствует: сравнивались две стратегии
  пересчёта, а не MV против таблицы.
  Bytes spilled to storage воспроизвести не удалось: DuckDB 1.4.3
  досчитывает агрегацию потоком и временных файлов не создаёт.

Next steps:
  1. Days 99-100 — Data Sharing + Marketplace, закрывают Неделю 13
  2. При появлении аккаунта: 15 -> 16 -> 17 -> 18 в Worksheet,
     затем сверить partitions_scanned из QUERY_HISTORY с таблицей
     из day97_98_clustering
  3. Концепты в базу: /ae-concept Query Profile, /ae-concept Clustering Keys,
     /ae-concept Result Cache, /ae-concept Materialized View

Git:
  git add lesson97_98.py snowflake_setup/1[5678]_*.sql reports/day97_98_*
  git commit -m "feat: Days 97-98 Performance Tuning"
""")


if __name__ == "__main__":
    main()
