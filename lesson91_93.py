#!/usr/bin/env python3
"""
lesson91_93.py — Days 91-93: Time Travel + Zero Copy Clone

Запуск:
    python lesson91_93.py

Открывает Месяц 4 (Snowflake Advanced). Продолжает дни 71-80.

Что делает:
  1. Пишет три SQL-скрипта под реальный Snowflake в snowflake_setup/
  2. Симулирует Time Travel в DuckDB: версионированная история строк,
     случайный DELETE и восстановление на момент времени
  3. Показывает, что UNDROP воспроизвести нельзя — и почему это вывод дня
  4. Замеряет стоимость обычной копии таблицы (CTAS) против Zero Copy Clone
  5. Складывает два CSV в reports/ + блок «На собеседовании»

Snowflake-аккаунта здесь нет — как в днях 71-80: реальные .sql лежат
готовыми к запуску в Worksheet, а механика отрабатывается локально.
Честная оговорка: Time Travel симулируется хуже, чем COPY INTO в дне 74.
Там был аналог, здесь аналога нет — есть только ручная реконструкция.
"""

import csv
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
REPORTS_DIR = PROJECT_ROOT / "reports"

SNOWFLAKE_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

SIM_DB = SNOWFLAKE_DIR / "snowflake_simulation.duckdb"
CLONE_DB = SNOWFLAKE_DIR / "clone_cost_demo.duckdb"

TODAY = datetime.now().strftime("%Y-%m-%d")

# Симулированные часы. Не time.time(): нужен воспроизводимый таймлайн,
# который можно печатать в отчёт и сверять между запусками.
T0 = datetime(2026, 8, 22, 10, 0, 0)   # первичная загрузка
T1 = T0 + timedelta(minutes=5)         # штатный UPDATE
T2 = T0 + timedelta(minutes=10)        # случайный DELETE
T3 = T0 + timedelta(minutes=15)        # восстановление

CLONE_ROWS = 300_000

SEP = "=" * 62


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")


def mb(num_bytes: int) -> float:
    return round(num_bytes / 1024 / 1024, 2)


# ═══════════════════════════════════════════════════════════
#  STEP 1 — SQL под реальный Snowflake
# ═══════════════════════════════════════════════════════════

TIME_TRAVEL_SQL = """\
-- snowflake_setup/09_time_travel.sql
-- Days 91-93: Time Travel — чтение прошлого состояния таблицы
-- Запуск: Snowflake Worksheet или SnowSQL

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- ─── 1. Сколько истории вообще доступно ───────────────────
-- Standard edition: 0 или 1 день. Enterprise: до 90 дней.
-- Ретенция настраивается на таблице, схеме или базе — наследуется вниз.
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS' IN TABLE orders;

ALTER TABLE orders SET DATA_RETENTION_TIME_IN_DAYS = 7;

-- ─── 2. Три способа указать точку во времени ──────────────

-- 2.1 AT TIMESTAMP — абсолютный момент
SELECT COUNT(*) AS rows_at_ts
FROM orders AT (TIMESTAMP => '2026-08-22 10:00:00'::TIMESTAMP_LTZ);

-- 2.2 AT OFFSET — относительный сдвиг в секундах, всегда отрицательный
SELECT COUNT(*) AS rows_15_min_ago
FROM orders AT (OFFSET => -60 * 15);

-- 2.3 BEFORE STATEMENT — состояние ДО конкретного запроса.
-- Самый точный вариант при инциденте: не надо угадывать секунды.
SELECT query_id, start_time, LEFT(query_text, 80) AS query_text
FROM TABLE(information_schema.query_history_by_session())
WHERE query_text ILIKE 'DELETE FROM ORDERS%'
ORDER BY start_time DESC
LIMIT 5;

SELECT COUNT(*) FROM orders BEFORE (STATEMENT => '<подставь query_id из запроса выше>');

-- ─── 3. Сценарий инцидента: случайный DELETE ──────────────

SELECT COUNT(*) AS before_delete FROM orders;

DELETE FROM orders WHERE amount < 50;          -- забыли вторую половину WHERE

SELECT COUNT(*) AS after_delete FROM orders;
SELECT COUNT(*) AS was_a_minute_ago FROM orders AT (OFFSET => -60);

-- 3.1 Точечное восстановление: вернуть только потерянные строки.
-- MINUS в Snowflake — синоним EXCEPT.
INSERT INTO orders
SELECT * FROM orders AT (OFFSET => -60)
MINUS
SELECT * FROM orders;

-- 3.2 Полная замена таблицы состоянием до сбойного запроса.
-- Обрывает Time Travel самой таблицы: у CREATE OR REPLACE история новая.
CREATE OR REPLACE TABLE orders AS
SELECT * FROM orders BEFORE (STATEMENT => '<query_id>');

-- ─── 4. UNDROP — восстановление удалённой таблицы ─────────
-- Работает в пределах окна ретенции. Схемы и базы тоже.

DROP TABLE orders;
SHOW TABLES HISTORY LIKE 'ORDERS';             -- колонка dropped_on
UNDROP TABLE orders;

-- Если после DROP уже создали новую таблицу с тем же именем,
-- UNDROP упадёт с конфликтом имён: сначала переименуй новую.
ALTER TABLE orders RENAME TO orders_new;
UNDROP TABLE orders;

-- ─── 5. Сколько это стоит ─────────────────────────────────
-- Time Travel — это хранение старых micro-partitions. Оно оплачивается.
SELECT
    table_schema,
    table_name,
    active_bytes / POW(1024, 3)      AS active_gb,
    time_travel_bytes / POW(1024, 3) AS time_travel_gb,
    failsafe_bytes / POW(1024, 3)    AS failsafe_gb
FROM snowflake.account_usage.table_storage_metrics
WHERE deleted = FALSE
ORDER BY time_travel_bytes DESC
LIMIT 20;
"""

ZERO_COPY_SQL = """\
-- snowflake_setup/10_zero_copy_clone.sql
-- Days 91-93: Zero Copy Clone — копия без копирования данных

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;

-- ─── 1. Клон таблицы ──────────────────────────────────────
-- Копируются метаданные: список указателей на micro-partitions.
-- Байты данных не дублируются. Время не зависит от размера таблицы.
CREATE TABLE raw.orders_backup CLONE raw.orders;

-- ─── 2. Клон схемы и базы ─────────────────────────────────
-- Так делается dev-окружение с полными prod-данными за секунды.
CREATE SCHEMA raw_dev CLONE raw;
CREATE DATABASE analytics_dev CLONE analytics_db;

-- ─── 3. Клон + Time Travel вместе ─────────────────────────
-- Самая полезная комбинация: воспроизвести баг на вчерашних данных,
-- не трогая prod.
CREATE TABLE raw.orders_yesterday CLONE raw.orders AT (OFFSET => -60 * 60 * 24);

CREATE DATABASE analytics_debug CLONE analytics_db
    BEFORE (STATEMENT => '<query_id сбойной загрузки>');

-- ─── 4. Copy-on-write: расходятся только изменённые партиции ──
UPDATE raw.orders_backup SET status = 'test' WHERE order_id < 100;

-- Оригинал не тронут:
SELECT status, COUNT(*) FROM raw.orders        GROUP BY 1;
SELECT status, COUNT(*) FROM raw.orders_backup GROUP BY 1;

-- Расход хранения появился только на изменённых micro-partitions.
-- clone_group_id связывает клоны, выросшие из одной таблицы.
SELECT
    table_name,
    clone_group_id,
    active_bytes / POW(1024, 2) AS active_mb
FROM snowflake.account_usage.table_storage_metrics
WHERE table_name IN ('ORDERS', 'ORDERS_BACKUP')
  AND deleted = FALSE;

-- ─── 5. Что клон НЕ наследует ─────────────────────────────
-- 5.1 GRANTS на таблице — по умолчанию нет. Нужен COPY GRANTS.
CREATE TABLE raw.orders_backup2 CLONE raw.orders COPY GRANTS;

-- 5.2 Внешние stage: клонируется определение, файлы в S3/GCS не копируются.
-- 5.3 Внутренние named stage не клонируются вовсе.
-- 5.4 У Snowpipe в клоне обнуляется история загруженных файлов.
-- 5.5 TEMPORARY и TRANSIENT таблицы нельзя клонировать в PERMANENT.

-- ─── 6. Уборка ────────────────────────────────────────────
-- Клоны выглядят бесплатными ровно до первой записи в них.
-- Забытый клон prod-базы месячной давности — это счёт за хранение.
DROP DATABASE IF EXISTS analytics_dev;
DROP DATABASE IF EXISTS analytics_debug;
"""

RETENTION_SQL = """\
-- snowflake_setup/11_retention_failsafe.sql
-- Days 91-93: ретенция, Fail-safe и типы таблиц

USE ROLE ACCOUNTADMIN;

-- ─── 1. Два разных механизма, их постоянно путают ─────────
--
--   Time Travel                          Fail-safe
--   ───────────────────────────────      ─────────────────────────────
--   0-90 дней, настраивается тобой       ровно 7 дней, не настраивается
--   доступен через SQL (AT / BEFORE)     доступен только через саппорт
--   для восстановления после ошибки      для восстановления после аварии
--   оплачивается как хранение            оплачивается как хранение
--
-- Fail-safe начинается там, где кончился Time Travel.
-- Восстановление из него — это тикет в Snowflake Support, не запрос.

-- ─── 2. Типы таблиц: ретенция и наличие Fail-safe ─────────
--
--   Тип         Time Travel      Fail-safe   Когда применять
--   ─────────   ──────────────   ─────────   ────────────────────────
--   PERMANENT   0-90 дней        7 дней      всё, что нельзя потерять
--   TRANSIENT   0-1 день         нет         staging, промежуточные слои
--   TEMPORARY   0-1 день         нет         живёт до конца сессии
--
-- TRANSIENT — прямой способ срезать счёт за хранение на слоях,
-- которые всегда можно пересобрать из raw.

CREATE TRANSIENT TABLE staging.stg_orders_tmp AS SELECT * FROM raw.orders;

-- ─── 3. Настройка ретенции на разных уровнях ──────────────
ALTER DATABASE analytics_db SET DATA_RETENTION_TIME_IN_DAYS = 7;
ALTER SCHEMA   staging      SET DATA_RETENTION_TIME_IN_DAYS = 1;
ALTER TABLE    raw.orders   SET DATA_RETENTION_TIME_IN_DAYS = 30;

-- Значение наследуется сверху вниз и переопределяется на любом уровне.
SELECT table_schema, table_name, retention_time
FROM analytics_db.information_schema.tables
WHERE table_type = 'BASE TABLE'
ORDER BY retention_time DESC;

-- ─── 4. Ретенция 0 отключает и Time Travel, и UNDROP ──────
-- Экономия на dev-схемах, но DROP становится необратимым.
ALTER SCHEMA scratch SET DATA_RETENTION_TIME_IN_DAYS = 0;

-- ─── 5. Куда уходят деньги ────────────────────────────────
SELECT
    SUM(active_bytes)      / POW(1024, 3) AS active_gb,
    SUM(time_travel_bytes) / POW(1024, 3) AS time_travel_gb,
    SUM(failsafe_bytes)    / POW(1024, 3) AS failsafe_gb
FROM snowflake.account_usage.table_storage_metrics
WHERE deleted = FALSE;

-- Если time_travel_gb сопоставим с active_gb — где-то таблица
-- с высокой ретенцией, которую переписывают целиком каждый день.
-- Лечится не уменьшением ретенции, а incremental-моделью в dbt.
"""


def step1_snowflake_sql():
    banner("STEP 1", "SQL-скрипты под реальный Snowflake")
    write_utf8(SNOWFLAKE_DIR / "09_time_travel.sql", TIME_TRAVEL_SQL)
    write_utf8(SNOWFLAKE_DIR / "10_zero_copy_clone.sql", ZERO_COPY_SQL)
    write_utf8(SNOWFLAKE_DIR / "11_retention_failsafe.sql", RETENTION_SQL)
    print("\n  Скрипты готовы к запуску в Worksheet при появлении аккаунта.")
    print("  Порядок: 09 -> 10 -> 11, они опираются на 01-08 из дней 71-80.")


# ═══════════════════════════════════════════════════════════
#  STEP 2 — Time Travel руками в DuckDB
# ═══════════════════════════════════════════════════════════

def build_baseline(con):
    """Исходная таблица + версионированная история к ней."""
    con.execute("CREATE SCHEMA IF NOT EXISTS time_travel")
    con.execute("DROP VIEW IF EXISTS time_travel.orders_hashed")
    con.execute("DROP TABLE IF EXISTS time_travel.orders")
    con.execute("DROP TABLE IF EXISTS time_travel.orders_history")

    con.execute("""
        CREATE TABLE time_travel.orders AS
        SELECT
            i                                            AS order_id,
            'customer_' || CAST((i % 25) + 1 AS VARCHAR) AS customer,
            'new'                                        AS status,
            ROUND(10 + ((i * 37) % 400), 2)              AS amount
        FROM range(1, 201) t(i)
    """)

    # row_hash — отпечаток изменяемых колонок. Ровно так же работает
    # dbt snapshot со стратегией check: сравнивать не даты, а содержимое.
    con.execute("""
        CREATE VIEW time_travel.orders_hashed AS
        SELECT order_id, customer, status, amount,
               md5(status || '|' || CAST(amount AS VARCHAR)) AS row_hash
        FROM time_travel.orders
    """)

    con.execute("""
        CREATE TABLE time_travel.orders_history (
            order_id   BIGINT,
            customer   VARCHAR,
            status     VARCHAR,
            amount     DOUBLE,
            row_hash   VARCHAR,
            valid_from TIMESTAMP,
            valid_to   TIMESTAMP
        )
    """)


def commit_version(con, ts: datetime) -> None:
    """Зафиксировать текущее состояние orders в истории на момент ts.

    Snowflake делает это сам на уровне micro-partitions при каждом DML.
    Здесь — вручную, в два шага: закрыть исчезнувшие версии, вставить новые.
    Порядок важен: если сначала вставлять, NOT EXISTS на втором шаге
    увидит только что вставленные строки и вставка станет пустой.
    """
    con.execute("DROP TABLE IF EXISTS close_ids")
    con.execute("""
        CREATE TEMP TABLE close_ids AS
        SELECT h.order_id
        FROM time_travel.orders_history h
        WHERE h.valid_to IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM time_travel.orders_hashed o
              WHERE o.order_id = h.order_id AND o.row_hash = h.row_hash)
    """)
    con.execute("""
        UPDATE time_travel.orders_history
        SET valid_to = ?
        WHERE valid_to IS NULL
          AND order_id IN (SELECT order_id FROM close_ids)
    """, [ts])
    con.execute("""
        INSERT INTO time_travel.orders_history
        SELECT o.order_id, o.customer, o.status, o.amount, o.row_hash, ?, NULL
        FROM time_travel.orders_hashed o
        WHERE NOT EXISTS (
            SELECT 1 FROM time_travel.orders_history h
            WHERE h.valid_to IS NULL
              AND h.order_id = o.order_id
              AND h.row_hash = o.row_hash)
    """, [ts])
    con.execute("DROP TABLE IF EXISTS close_ids")


AS_OF_PREDICATE = "valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)"


def count_as_of(con, ts: datetime) -> int:
    """Аналог SELECT COUNT(*) FROM orders AT (TIMESTAMP => ts)."""
    sql = f"SELECT COUNT(*) FROM time_travel.orders_history WHERE {AS_OF_PREDICATE}"
    return con.execute(sql, [ts, ts]).fetchone()[0]


def status_as_of(con, ts: datetime) -> dict:
    sql = f"""
        SELECT status, COUNT(*)
        FROM time_travel.orders_history
        WHERE {AS_OF_PREDICATE}
        GROUP BY 1 ORDER BY 1
    """
    return dict(con.execute(sql, [ts, ts]).fetchall())


def step2_time_travel(con) -> list:
    banner("STEP 2", "Time Travel: версии, инцидент, восстановление")
    timeline = []

    def record(ts, label, sf_command):
        current = con.execute("SELECT COUNT(*) FROM time_travel.orders").fetchone()[0]
        at_ts = count_as_of(con, ts)
        statuses = status_as_of(con, ts)
        timeline.append({
            "moment": ts.strftime("%H:%M"),
            "event": label,
            "rows_current": current,
            "rows_at_moment": at_ts,
            "statuses_at_moment": "; ".join(f"{k}={v}" for k, v in statuses.items()),
            "snowflake_command": sf_command,
        })
        print(f"  {ts:%H:%M}  {label:<36} строк: {at_ts:>3}  ({statuses})")

    print("\n  2.1 Таймлайн\n")
    build_baseline(con)
    commit_version(con, T0)
    record(T0, "первичная загрузка, 200 заказов",
           "COPY INTO orders FROM @stage")

    con.execute("UPDATE time_travel.orders SET status = 'shipped' WHERE order_id % 5 = 0")
    commit_version(con, T1)
    record(T1, "UPDATE: 40 заказов -> shipped",
           "UPDATE orders SET status='shipped' WHERE ...")

    deleted = con.execute(
        "SELECT COUNT(*) FROM time_travel.orders WHERE amount < 50").fetchone()[0]
    con.execute("DELETE FROM time_travel.orders WHERE amount < 50")
    commit_version(con, T2)
    record(T2, f"случайный DELETE: -{deleted} строк",
           "DELETE FROM orders WHERE amount < 50")

    print("\n  2.2 Взгляд в прошлое из настоящего")
    now_rows = con.execute("SELECT COUNT(*) FROM time_travel.orders").fetchone()[0]
    print(f"    сейчас в таблице             : {now_rows}")
    print(f"    было на {T1:%H:%M} (до DELETE)     : {count_as_of(con, T1)}")
    print(f"    было на {T0:%H:%M} (до UPDATE)     : {count_as_of(con, T0)}")
    print("    Snowflake: SELECT COUNT(*) FROM orders AT (OFFSET => -600);")

    print("\n  2.3 Восстановление на момент до инцидента")
    con.execute("DELETE FROM time_travel.orders")
    con.execute(f"""
        INSERT INTO time_travel.orders
        SELECT order_id, customer, status, amount
        FROM time_travel.orders_history
        WHERE {AS_OF_PREDICATE}
    """, [T1, T1])
    commit_version(con, T3)
    record(T3, "восстановлено на 10:05",
           "INSERT INTO orders SELECT * FROM orders AT(...) MINUS SELECT * FROM orders")

    restored = con.execute("SELECT COUNT(*) FROM time_travel.orders").fetchone()[0]
    diff = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT order_id, status, amount FROM time_travel.orders
            EXCEPT
            SELECT order_id, status, amount FROM time_travel.orders_history
            WHERE {AS_OF_PREDICATE}
        )
    """, [T1, T1]).fetchone()[0]
    print(f"    строк после восстановления   : {restored}")
    print(f"    расхождений с состоянием {T1:%H:%M}: {diff}")
    assert restored == 200 and diff == 0, "восстановление не сошлось"
    print("    OK  состояние совпало с точкой во времени")

    return timeline


def step3_undrop(con):
    banner("STEP 3", "UNDROP: то, что симулировать нельзя")

    con.execute("DROP VIEW IF EXISTS time_travel.orders_hashed")
    con.execute("DROP TABLE time_travel.orders")
    exists = con.execute("""
        SELECT COUNT(*) FROM duckdb_tables()
        WHERE schema_name = 'time_travel' AND table_name = 'orders'
    """).fetchone()[0]
    print(f"  после DROP TABLE таблица существует: {bool(exists)}")
    print("  В DuckDB после DROP не осталось ничего: ни истории партиций,")
    print("  ни списка удалённых объектов. Восстанавливать нечего.")

    con.execute("""
        CREATE TABLE time_travel.orders AS
        SELECT order_id, customer, status, amount
        FROM time_travel.orders_history
        WHERE valid_to IS NULL
    """)
    con.execute("""
        CREATE VIEW time_travel.orders_hashed AS
        SELECT order_id, customer, status, amount,
               md5(status || '|' || CAST(amount AS VARCHAR)) AS row_hash
        FROM time_travel.orders
    """)
    rows = con.execute("SELECT COUNT(*) FROM time_travel.orders").fetchone()[0]
    print(f"  восстановлено из orders_history вручную: {rows} строк")
    print("\n  Вывод дня: сработало только потому, что историю вели мы сами.")
    print("  Snowflake на этом месте — одна команда:  UNDROP TABLE orders;")
    print("  Ни отдельной таблицы истории, ни ETL под неё не нужно.")


# ═══════════════════════════════════════════════════════════
#  STEP 4 — сколько стоит копия таблицы
# ═══════════════════════════════════════════════════════════

def step4_clone_cost() -> dict:
    banner("STEP 4", "Zero Copy Clone: замер стоимости обычной копии")

    if CLONE_DB.exists():
        CLONE_DB.unlink()

    con = duckdb.connect(str(CLONE_DB))
    try:
        # Заполнитель из md5 — высокоэнтропийные строки, чтобы сжатие
        # не съело разницу и замер отражал реальный объём данных.
        con.execute(f"""
            CREATE TABLE orders_big AS
            SELECT
                i                                        AS order_id,
                'customer_' || CAST(i % 5000 AS VARCHAR) AS customer,
                ROUND(10 + ((i * 37) % 5000), 2)         AS amount,
                md5(CAST(i AS VARCHAR))                  AS payload
            FROM range(1, {CLONE_ROWS + 1}) t(i)
        """)
        con.execute("CHECKPOINT")
        size_source = CLONE_DB.stat().st_size
        print(f"  исходная таблица : {CLONE_ROWS:,} строк, файл БД {mb(size_source)} МБ")

        started = time.perf_counter()
        con.execute("CREATE TABLE orders_big_copy AS SELECT * FROM orders_big")
        con.execute("CHECKPOINT")
        elapsed = time.perf_counter() - started
        size_after = CLONE_DB.stat().st_size
        grew = max(size_after - size_source, 1)

        print(f"  CTAS-копия       : {elapsed:.2f} с, файл вырос на {mb(grew)} МБ")

        # Семантика клона: запись в копию не задевает оригинал.
        con.execute("UPDATE orders_big_copy SET amount = -1 WHERE order_id <= 100")
        src_touched = con.execute(
            "SELECT COUNT(*) FROM orders_big WHERE amount = -1").fetchone()[0]
        print(f"  строк испорчено в оригинале после UPDATE копии: {src_touched}")

        # Экстраполяция на боевой объём.
        per_row = grew / CLONE_ROWS
        proj_100m = per_row * 100_000_000 / 1024 ** 3
        proj_time = elapsed * (100_000_000 / CLONE_ROWS) / 60

        print("\n  Пересчёт на таблицу в 100 млн строк:")
        print(f"    копия через CTAS      : ~{proj_100m:.1f} ГБ, ~{proj_time:.0f} мин")
        print("    Zero Copy Clone       : 0 байт данных, ~1 секунда")
        print("\n  Клон копирует список указателей на micro-partitions,")
        print("  а не сами партиции. Время не зависит от размера таблицы,")
        print("  расход хранения появляется только на изменённых партициях.")

        return {
            "rows": CLONE_ROWS,
            "ctas_seconds": round(elapsed, 2),
            "ctas_growth_mb": mb(grew),
            "source_untouched": src_touched == 0,
            "projected_100m_gb": round(proj_100m, 1),
            "projected_100m_minutes": round(proj_time),
        }
    finally:
        con.close()
        if CLONE_DB.exists():
            CLONE_DB.unlink()


# ═══════════════════════════════════════════════════════════
#  STEP 5 — артефакты
# ═══════════════════════════════════════════════════════════

def step5_reports(timeline: list, clone: dict) -> list:
    banner("STEP 5", "Отчёты в reports/")

    tl_path = REPORTS_DIR / f"day91_93_time_travel_timeline_{TODAY}.csv"
    with tl_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(timeline[0].keys()))
        writer.writeheader()
        writer.writerows(timeline)
    print(f"  OK  {tl_path.relative_to(PROJECT_ROOT)}  ({len(timeline)} версий)")

    cost_rows = [
        {
            "feature": "Копия таблицы",
            "duckdb_local": f"CTAS: +{clone['ctas_growth_mb']} МБ за "
                            f"{clone['ctas_seconds']} с на {clone['rows']:,} строк",
            "snowflake": "CREATE TABLE ... CLONE ...: 0 байт данных, ~1 с",
            "measured": f"на 100 млн строк: ~{clone['projected_100m_gb']} ГБ / "
                        f"~{clone['projected_100m_minutes']} мин против 0 / 1 с",
        },
        {
            "feature": "Чтение прошлого состояния",
            "duckdb_local": "своя таблица истории valid_from/valid_to + row_hash",
            "snowflake": "orders AT (TIMESTAMP =>) / AT (OFFSET =>) / BEFORE (STATEMENT =>)",
            "measured": "восстановление на точку 10:05 сошлось, расхождений 0",
        },
        {
            "feature": "Восстановление удалённой таблицы",
            "duckdb_local": "невозможно: после DROP не остаётся ничего",
            "snowflake": "UNDROP TABLE orders",
            "measured": "воспроизведено вручную из orders_history",
        },
        {
            "feature": "Окно восстановления",
            "duckdb_local": "сколько сам хранишь",
            "snowflake": "Time Travel 0-90 дней + Fail-safe ровно 7 дней",
            "measured": "Standard edition — 1 день, Enterprise — до 90",
        },
        {
            "feature": "Изоляция копии при записи",
            "duckdb_local": "полная: данные физически разные",
            "snowflake": "copy-on-write, расходятся только изменённые micro-partitions",
            "measured": f"оригинал не тронут: {clone['source_untouched']}",
        },
    ]
    cost_path = REPORTS_DIR / f"day91_93_clone_cost_{TODAY}.csv"
    with cost_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(cost_rows[0].keys()))
        writer.writeheader()
        writer.writerows(cost_rows)
    print(f"  OK  {cost_path.relative_to(PROJECT_ROOT)}  ({len(cost_rows)} строк)")

    return [tl_path, cost_path]


def step6_interview():
    banner("STEP 6", "На собеседовании")
    print("""
  «Продакшен-таблицу почистили лишним DELETE час назад. Действия?»

    Сначала найти query_id сбойного запроса в query_history, а не гадать
    со временем: BEFORE (STATEMENT => ...) точнее, чем AT (OFFSET => ...).
    Потом сравнить состояние до и после и вернуть разницу через
    INSERT ... SELECT ... MINUS — это не обрывает Time Travel таблицы,
    в отличие от CREATE OR REPLACE. И только после — разбор, почему
    DELETE ушёл в прод без ограничения в WHERE и без dry-run.

  «Чем Time Travel отличается от Fail-safe?»

    Time Travel — твой инструмент: 0-90 дней, настраивается параметром,
    доступен обычным SQL. Fail-safe — не твой: ровно 7 дней после того,
    как Time Travel кончился, доступ только через саппорт, срок и цена
    не регулируются. Fail-safe — страховка Snowflake от аварии, а не
    механизм отката твоих ошибок. Планировать надо на Time Travel.

  «Зачем Zero Copy Clone, если есть CTAS?»

    Клон копирует метаданные, а не данные: время не зависит от размера,
    хранение не удваивается. Отсюда практика — dev-окружение как клон
    prod целиком и отладочный клон на состояние до сбоя через
    CLONE ... BEFORE (STATEMENT => ...). Подвох на собеседовании один:
    клон не бесплатен навсегда — при записи расходятся изменённые
    micro-partitions, а забытый клон базы продолжает стоить денег.

  «Как срезать счёт за хранение, не теряя надёжности?»

    Разделить слои по типам таблиц: raw остаётся PERMANENT с ретенцией
    7-30 дней, staging и промежуточные слои — TRANSIENT, у них нет
    Fail-safe и максимум 1 день Time Travel. Они всегда пересобираются
    из raw, платить за их историю незачем. Второй источник расходов —
    таблицы, которые переписываются целиком каждый день: там Time Travel
    растёт линейно, и лечится это incremental-моделью в dbt, а не
    снижением ретенции.
""")


def main():
    print(SEP)
    print("  lesson91_93.py — Days 91-93: Time Travel + Zero Copy Clone")
    print(SEP)

    step1_snowflake_sql()

    con = duckdb.connect(str(SIM_DB))
    try:
        timeline = step2_time_travel(con)
        step3_undrop(con)
    finally:
        con.close()

    clone = step4_clone_cost()
    artifacts = step5_reports(timeline, clone)
    step6_interview()

    print(SEP)
    print("  ALL DONE")
    print(SEP)
    print(f"""
Артефакты:
  snowflake_setup/09_time_travel.sql
  snowflake_setup/10_zero_copy_clone.sql
  snowflake_setup/11_retention_failsafe.sql
  {artifacts[0].relative_to(PROJECT_ROOT)}
  {artifacts[1].relative_to(PROJECT_ROOT)}

Что осталось несделанным честно:
  Snowflake-аккаунта нет — скрипты 09-11 написаны, но не выполнялись.
  UNDROP и Fail-safe локально не проверяются в принципе.

Next steps:
  1. Days 94-96 — Streams + Tasks (CDC внутри Snowflake)
  2. При появлении аккаунта: прогнать 09 -> 10 -> 11 в Worksheet
  3. Концепты в базу: /ae-concept Time Travel, /ae-concept Zero Copy Clone

Git:
  git add snowflake_setup/ lesson91_93.py reports/day91_93_*
  git commit -m "feat: Days 91-93 Time Travel + Zero Copy Clone"
""")


if __name__ == "__main__":
    main()
