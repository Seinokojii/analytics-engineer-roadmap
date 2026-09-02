#!/usr/bin/env python3
"""
lesson94_96.py — Days 94-96: Streams + Tasks

Запуск:
    python lesson94_96.py

Продолжает дни 91-93. Тот же принцип: Snowflake-аккаунта нет, поэтому
реальные .sql пишутся готовыми к запуску в Worksheet, а механика
отрабатывается локально на DuckDB.

Что делает:
  1. Пишет три SQL-скрипта под реальный Snowflake в snowflake_setup/
  2. Симулирует Stream честно: offset + diff по row_hash, а не журнал.
     Показывает METADATA$ACTION / METADATA$ISUPDATE / схлопывание
     INSERT+DELETE и то, что SELECT не двигает offset
  3. Два стрима на одну таблицу — почему один стрим на потребителя
  4. Append-only stream против standard: что теряется и что дешевеет
  5. Симулирует граф Tasks: WHEN, пропуск запуска, падение ребёнка
  6. Кладёт три CSV в reports/ + блок «На собеседовании»

Что здесь симулируется хуже оригинала — честно:
  Stale stream (протухание по DATA_RETENTION_TIME_IN_DAYS) проверяется
  по возрасту снимка, а не по реальной ретенции micro-partitions.
  Snowpipe не симулируется вообще: нет ни S3, ни очереди событий.
"""

import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
REPORTS_DIR = PROJECT_ROOT / "reports"

SNOWFLAKE_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

SIM_DB = SNOWFLAKE_DIR / "streams_tasks_demo.duckdb"

TODAY = datetime.now().strftime("%Y-%m-%d")

# Симулированные часы: нужен воспроизводимый таймлайн для отчётов.
T0 = datetime(2026, 9, 2, 9, 0, 0)

SEP = "=" * 62

# Колонки таблицы raw.orders. Порядок важен: по нему считается row_hash.
ORDER_COLS = ["order_id", "user_id", "amount", "city", "status", "updated_at"]


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")


def row_hash_expr(alias: str) -> str:
    """SQL-выражение хеша строки. Аналог того, как Snowflake сравнивает
    состояния: нам важен не сам хеш, а факт «строка изменилась»."""
    parts = [f"COALESCE(CAST({alias}.{c} AS VARCHAR), '~')" for c in ORDER_COLS]
    return "md5(concat_ws('|', " + ", ".join(parts) + "))"


# ═══════════════════════════════════════════════════════════
#  STEP 1 — SQL под реальный Snowflake
# ═══════════════════════════════════════════════════════════

STREAMS_SQL = """\
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
"""

TASKS_SQL = """\
-- snowflake_setup/13_tasks.sql
-- Days 94-96: Tasks — планировщик внутри Snowflake
-- Запуск: Snowflake Worksheet или SnowSQL

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- Task требует отдельной привилегии на уровне аккаунта:
-- GRANT EXECUTE TASK ON ACCOUNT TO ROLE SYSADMIN;

-- ─── 1. Root task: расписание + условие ───────────────────
-- SCHEDULE задаётся ЛИБО интервалом, ЛИБО cron. Не обоими сразу.
CREATE OR REPLACE TASK t_load_stg
    WAREHOUSE = analytics_wh
    SCHEDULE  = 'USING CRON 0 * * * * UTC'   -- каждый час
    -- альтернатива: SCHEDULE = '60 MINUTE'
WHEN
    SYSTEM$STREAM_HAS_DATA('orders_stream_stg')
AS
    INSERT INTO staging.stg_orders (order_id, user_id, amount, city, order_date)
    SELECT order_id, user_id, amount, city, updated_at::DATE
    FROM orders_stream_stg
    WHERE METADATA$ACTION = 'INSERT'
      AND status = 'completed';

-- WHEN — не косметика, а деньги: если условие ложно, задача
-- переходит в SKIPPED и warehouse не просыпается. Проверка
-- SYSTEM$STREAM_HAS_DATA бесплатна, запуск warehouse — нет.

-- ─── 2. Serverless task: без своего warehouse ─────────────
-- Убрать WAREHOUSE → Snowflake сам подбирает compute и биллит
-- посекундно. Дешевле для коротких частых задач: нет 60-секундного
-- минимума и времени прогрева. Дороже для тяжёлых.
CREATE OR REPLACE TASK t_load_stg_serverless
    USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
    SCHEDULE = '5 MINUTE'
AS
    CALL some_procedure();

-- ─── 3. Граф задач: AFTER ─────────────────────────────────
-- Расписание есть ТОЛЬКО у корня. У детей — зависимость.
CREATE OR REPLACE TASK t_build_marts
    WAREHOUSE = analytics_wh
    AFTER t_load_stg
AS
    INSERT INTO marts.daily_revenue (order_date, revenue)
    SELECT order_date, SUM(amount)
    FROM staging.stg_orders
    GROUP BY 1;

CREATE OR REPLACE TASK t_audit_log
    WAREHOUSE = analytics_wh
    AFTER t_load_stg
AS
    INSERT INTO ops.pipeline_audit (run_ts, rows_loaded)
    SELECT CURRENT_TIMESTAMP(), COUNT(*) FROM staging.stg_orders;

-- Задача с несколькими AFTER стартует, когда завершились ВСЕ родители.
CREATE OR REPLACE TASK t_notify
    WAREHOUSE = analytics_wh
    AFTER t_build_marts, t_audit_log
AS
    CALL ops.send_slack_alert('pipeline ok');

-- ─── 4. Запуск и остановка ────────────────────────────────
-- Созданная задача СОЗДАЁТСЯ ПРИОСТАНОВЛЕННОЙ. Забыть RESUME —
-- самая частая причина «таск не работает».
-- Порядок обязателен: сначала дети, потом корень.
ALTER TASK t_notify      RESUME;
ALTER TASK t_build_marts RESUME;
ALTER TASK t_audit_log   RESUME;
ALTER TASK t_load_stg    RESUME;   -- корень последним

-- Правка ребёнка требует остановки КОРНЯ, а не самого ребёнка.
ALTER TASK t_load_stg SUSPEND;

-- Ручной прогон всего графа, не дожидаясь расписания:
EXECUTE TASK t_load_stg;

-- ─── 5. Пересечение запусков ──────────────────────────────
-- По умолчанию ALLOW_OVERLAPPING_EXECUTION = FALSE: если предыдущий
-- прогон графа ещё идёт, очередной запуск по расписанию
-- ПРОПУСКАЕТСЯ молча. Задача, которая дольше своего интервала,
-- тихо теряет запуски — ловится только в task_history.
ALTER TASK t_load_stg SET ALLOW_OVERLAPPING_EXECUTION = FALSE;

-- Защита от вечно висящей задачи:
ALTER TASK t_load_stg SET USER_TASK_TIMEOUT_MS = 3600000;   -- 1 час

-- ─── 6. Finalizer: что выполнить после графа в любом случае ─
CREATE OR REPLACE TASK t_cleanup
    WAREHOUSE = analytics_wh
    FINALIZE = t_load_stg
AS
    CALL ops.release_locks();

-- ─── 7. Наблюдаемость ─────────────────────────────────────
SELECT name, state, scheduled_time, completed_time, error_message,
       DATEDIFF('second', scheduled_time, completed_time) AS duration_s
FROM TABLE(information_schema.task_history(
        SCHEDULED_TIME_RANGE_START => DATEADD('day', -1, CURRENT_TIMESTAMP())))
ORDER BY scheduled_time DESC;

-- state: SUCCEEDED | FAILED | SKIPPED | CANCELLED
-- SKIPPED — это WHEN вернул FALSE или пересечение запусков.
-- Отличать SKIPPED от FAILED обязательно: первое штатно, второе нет.

SELECT SYSTEM$TASK_DEPENDENTS_ENABLE('t_load_stg');

-- Алерты о падениях — через notification integration:
ALTER TASK t_load_stg SET ERROR_INTEGRATION = my_email_int;
"""

SNOWPIPE_SQL = """\
-- snowflake_setup/14_snowpipe.sql
-- Days 94-96: Snowpipe — continuous загрузка по событию
-- Запуск: Snowflake Worksheet или SnowSQL
-- Продолжает 06_stage_copy_into.sql из дней 74-75.

USE ROLE SYSADMIN;
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
USE SCHEMA raw;

-- ─── 1. Чем PIPE отличается от COPY INTO ──────────────────
-- COPY INTO   — ты решаешь, когда грузить. Нужен warehouse.
-- Snowpipe    — грузит сам, когда файл появился в стейдже.
--               Своего warehouse нет: serverless, биллинг за
--               обработанные файлы, отдельной строкой в счёте.
-- Задержка Snowpipe — минуты, не секунды. Это не стриминг.
-- Нужны секунды → Snowpipe Streaming API, другой продукт.

CREATE OR REPLACE STAGE orders_stage
    URL = 's3://my-bucket/orders/'
    STORAGE_INTEGRATION = s3_int
    FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1);

-- ─── 2. Сам pipe ──────────────────────────────────────────
CREATE OR REPLACE PIPE orders_pipe
    AUTO_INGEST = TRUE
AS
    COPY INTO raw.orders (order_id, user_id, amount, city, status, updated_at)
    FROM @orders_stage
    FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1)
    ON_ERROR = CONTINUE;

-- AUTO_INGEST = TRUE требует уведомлений от облака.
-- notification_channel из вывода ниже — ARN очереди SQS,
-- который прописывается в S3 Event Notification на стороне AWS.
SHOW PIPES LIKE 'orders_pipe';

-- ─── 3. Дедупликация файлов ───────────────────────────────
-- Pipe помнит загруженные файлы 14 дней и повторно их не берёт.
-- Отсюда два следствия:
--   * перезалить тот же файл в течение 14 дней — он будет
--     проигнорирован. Нужен REFRESH или новое имя.
--   * файл старше 14 дней при повторной заливке загрузится снова
--     и задвоит данные.
ALTER PIPE orders_pipe REFRESH;
ALTER PIPE orders_pipe REFRESH PREFIX = '2026/09/' MODIFIED_AFTER = '2026-09-01';

-- ─── 4. Наблюдаемость ─────────────────────────────────────
SELECT SYSTEM$PIPE_STATUS('orders_pipe');
-- executionState: RUNNING | STOPPED_*  ·  pendingFileCount  ·  lastReceivedMessageTimestamp
-- pendingFileCount растёт и не падает → уведомления идут, а загрузка встала.
-- lastReceivedMessageTimestamp старый → уведомления вообще не доходят,
-- проблема на стороне S3/SQS, а не Snowflake.

SELECT file_name, status, row_count, row_parsed, first_error_message,
       last_load_time
FROM TABLE(information_schema.copy_history(
        TABLE_NAME => 'raw.orders',
        START_TIME => DATEADD('hour', -24, CURRENT_TIMESTAMP())))
ORDER BY last_load_time DESC;

ALTER PIPE orders_pipe SET PIPE_EXECUTION_PAUSED = TRUE;

-- ─── 5. Полная event-driven цепочка ───────────────────────
-- S3 файл → SQS → PIPE → raw.orders → STREAM → TASK → staging → marts
-- Ни одного внешнего оркестратора. Вся цепочка живёт в Snowflake.
-- Плата за это — наблюдаемость размазана по трём разным местам:
-- copy_history, SHOW STREAMS, task_history.

-- ─── 6. Экономика ─────────────────────────────────────────
-- Snowpipe берёт накладные расходы за КАЖДЫЙ файл. Тысяча файлов
-- по 1 КБ обойдётся дороже одного файла на 1 МБ при том же объёме.
-- Рекомендация Snowflake: файлы 100-250 МБ сжатыми.
SELECT pipe_name, SUM(credits_used) AS credits, SUM(files_inserted) AS files
FROM snowflake.account_usage.pipe_usage_history
WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1;
"""


def step1_snowflake_sql():
    banner("STEP 1", "SQL под реальный Snowflake")
    write_utf8(SNOWFLAKE_DIR / "12_streams.sql", STREAMS_SQL)
    write_utf8(SNOWFLAKE_DIR / "13_tasks.sql", TASKS_SQL)
    write_utf8(SNOWFLAKE_DIR / "14_snowpipe.sql", SNOWPIPE_SQL)
    print("\n  Аккаунта нет — скрипты не выполнялись. Готовы к Worksheet.")


# ═══════════════════════════════════════════════════════════
#  Движок симуляции стрима
#
#  Stream в Snowflake — это offset плюс правило «покажи разницу
#  между состоянием на offset и текущим». Значит локально его
#  честно воспроизводит снимок таблицы на момент offset и diff
#  по row_hash. Не приблизительная аналогия — та же семантика.
# ═══════════════════════════════════════════════════════════

COLS = ", ".join(ORDER_COLS)


def create_stream(con, name: str) -> None:
    """CREATE STREAM: offset = «сейчас», поэтому свежий стрим пуст."""
    con.execute(f"CREATE OR REPLACE TABLE _offset_{name} AS SELECT * FROM orders")


def read_stream(con, name: str, append_only: bool = False):
    """SELECT из стрима. Offset НЕ двигает — сколько ни читай."""
    cur = f"SELECT {COLS}, {row_hash_expr('o')} AS _h FROM orders o"
    off = f"SELECT {COLS}, {row_hash_expr('o')} AS _h FROM _offset_{name} o"

    inserts = f"""
        SELECT 'INSERT' AS action, FALSE AS is_update, {COLS}
        FROM cur WHERE order_id NOT IN (SELECT order_id FROM off)"""

    if append_only:
        # APPEND_ONLY видит только появление новых строк.
        # UPDATE и DELETE для него не существуют.
        body = inserts
    else:
        body = f"""{inserts}
        UNION ALL
        SELECT 'DELETE', FALSE, {COLS}
        FROM off WHERE order_id NOT IN (SELECT order_id FROM cur)
        UNION ALL
        -- UPDATE приезжает ПАРОЙ строк, а не одной
        SELECT 'DELETE', TRUE, {", ".join("off." + c for c in ORDER_COLS)}
        FROM off JOIN cur ON off.order_id = cur.order_id AND off._h <> cur._h
        UNION ALL
        SELECT 'INSERT', TRUE, {", ".join("cur." + c for c in ORDER_COLS)}
        FROM off JOIN cur ON off.order_id = cur.order_id AND off._h <> cur._h"""

    sql = f"WITH cur AS ({cur}), off AS ({off}) {body} ORDER BY order_id, action"
    return con.execute(sql).fetchall()


def consume_stream(con, name: str) -> None:
    """Продвижение offset. В Snowflake это делает не SELECT, а
    успешно закоммиченная транзакция с DML поверх стрима."""
    con.execute(f"CREATE OR REPLACE TABLE _offset_{name} AS SELECT * FROM orders")


def show_stream(rows, title: str) -> None:
    print(f"\n  {title}: {len(rows)} строк")
    if not rows:
        print("    (пусто)")
        return
    print("    ACTION  ISUPDATE  order_id  amount   status")
    for action, is_upd, oid, _uid, amount, _city, status, _ts in rows:
        flag = "TRUE " if is_upd else "FALSE"
        print(f"    {action:<7} {flag:<9} {oid:<9} {amount:<8} {status}")


# ═══════════════════════════════════════════════════════════
#  STEP 2 — механика стрима
# ═══════════════════════════════════════════════════════════

SEED = [
    (1001, 11, 120.00, "Almaty", "completed"),
    (1002, 12, 340.50, "Astana", "completed"),
    (1003, 11, 89.90, "Almaty", "pending"),
    (1004, 13, 512.00, "Shymkent", "completed"),
    (1005, 14, 45.00, "Astana", "pending"),
    (1006, 12, 730.25, "Almaty", "completed"),
    (1007, 15, 210.00, "Karaganda", "completed"),
    (1008, 13, 96.40, "Shymkent", "completed"),
]


def step2_stream_mechanics(con):
    banner("STEP 2", "Механика стрима: offset, diff, METADATA")

    con.execute("DROP TABLE IF EXISTS orders")
    con.execute("""
        CREATE TABLE orders (
            order_id   INTEGER,
            user_id    INTEGER,
            amount     DECIMAL(10, 2),
            city       VARCHAR,
            status     VARCHAR,
            updated_at TIMESTAMP
        )
    """)
    for oid, uid, amount, city, status in SEED:
        con.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            [oid, uid, amount, city, status, T0],
        )
    print(f"  Загружено в raw.orders: {len(SEED)} строк, offset-точка {T0:%H:%M}")

    # Три стрима на одну таблицу. У каждого свой независимый offset.
    for name in ("stg", "audit", "events"):
        create_stream(con, name)
    print("  Созданы стримы: stg (standard), audit (standard), events (append-only)")

    fresh = read_stream(con, "stg")
    print(f"\n  Свежий стрим сразу после CREATE: {len(fresh)} строк — offset = «сейчас»")

    # ─── DML поверх таблицы ───────────────────────────────
    t1 = T0 + timedelta(minutes=20)
    dml = [
        ("INSERT", "INSERT INTO orders VALUES (1009, 16, 150.00, 'Almaty', 'completed', ?)", [t1]),
        ("INSERT", "INSERT INTO orders VALUES (1010, 11, 87.30, 'Astana', 'pending', ?)", [t1]),
        ("INSERT", "INSERT INTO orders VALUES (1011, 17, 999.00, 'Almaty', 'completed', ?)", [t1]),
        ("UPDATE", "UPDATE orders SET amount = 355.00, updated_at = ? WHERE order_id = 1002", [t1]),
        ("UPDATE", "UPDATE orders SET status = 'completed', updated_at = ? WHERE order_id = 1005", [t1]),
        ("DELETE", "DELETE FROM orders WHERE order_id = 1007", []),
        # Вставили и тут же удалили — проверка на схлопывание
        ("INSERT", "INSERT INTO orders VALUES (1012, 18, 33.00, 'Astana', 'pending', ?)", [t1]),
        ("DELETE", "DELETE FROM orders WHERE order_id = 1012", []),
    ]
    print(f"\n  DML в {t1:%H:%M}: 4 INSERT, 2 UPDATE, 2 DELETE (одна пара — на одной строке)")
    for _kind, sql, params in dml:
        con.execute(sql, params)

    rows = read_stream(con, "stg")
    show_stream(rows, "Standard stream orders_stream_stg")

    inserts = [r for r in rows if r[0] == "INSERT" and not r[1]]
    deletes = [r for r in rows if r[0] == "DELETE" and not r[1]]
    updates = [r for r in rows if r[1]]

    mech_dml = len(dml)
    print(f"""
  Разбор вывода:
    чистых INSERT       {len(inserts)}  — 1009, 1010, 1011
    чистых DELETE       {len(deletes)}  — 1007
    строк от UPDATE     {len(updates)}  — ДВА обновления, но ЧЕТЫРЕ строки
    заказ 1012          {"НЕ ВИДЕН" if all(r[2] != 1012 for r in rows) else "виден"} — вставлен и удалён между чтениями

  Стрим показывает net change, а не журнал операций. {mech_dml} DML-команд
  превратились в {len(rows)} строк — равенство случайное: одна вставка
  схлопнулась с удалением, зато каждое обновление дало по две строки.
  Нужен полный журнал — это CHANGES или таблица-аудит, стрим для
  этого не предназначен.""")

    # ─── Повторное чтение ─────────────────────────────────
    again = read_stream(con, "stg")
    print(f"\n  Повторный SELECT из стрима: {len(again)} строк — "
          f"{'то же самое, offset не сдвинулся' if len(again) == len(rows) else 'РАСХОЖДЕНИЕ'}")

    return {
        "dml_ops": len(dml),
        "stream_rows": len(rows),
        "inserts": len(inserts),
        "deletes": len(deletes),
        "update_rows": len(updates),
        "collapsed_1012": all(r[2] != 1012 for r in rows),
        "reread_stable": len(again) == len(rows),
    }


# ═══════════════════════════════════════════════════════════
#  STEP 3 — один стрим = один потребитель
# ═══════════════════════════════════════════════════════════

def step3_one_consumer_per_stream(con):
    banner("STEP 3", "Почему один стрим = один потребитель")

    before_stg = read_stream(con, "stg")
    before_audit = read_stream(con, "audit")
    print(f"  До потребления: stg = {len(before_stg)} строк, audit = {len(before_audit)} строк")

    # Потребитель №1: загрузка в staging. Внутри DML — значит offset сдвинется.
    con.execute("DROP TABLE IF EXISTS stg_orders")
    con.execute("CREATE TABLE stg_orders (order_id INTEGER, amount DECIMAL(10,2), city VARCHAR)")
    loaded = [r for r in before_stg if r[0] == "INSERT" and r[6] == "completed"]
    for r in loaded:
        con.execute("INSERT INTO stg_orders VALUES (?, ?, ?)", [r[2], r[4], r[5]])
    consume_stream(con, "stg")
    print(f"  Потребитель 1 (staging) — забрано строк: {len(loaded)}, транзакция закоммичена")

    after_stg = read_stream(con, "stg")
    after_audit = read_stream(con, "audit")
    print(f"  После:          stg = {len(after_stg)} строк, audit = {len(after_audit)} строк")

    print(f"""
  Вывод: offset сдвинулся ТОЛЬКО у того стрима, который участвовал
  в DML. Стрим audit не тронут — у него свой независимый указатель,
  он по-прежнему видит все {len(after_audit)} изменений.

  Если бы оба потребителя читали один стрим, второй получил бы пусто
  и данные были бы потеряны молча — без ошибки, без алерта. Это
  тихая потеря данных, самый неприятный класс багов в пайплайне.

  Практическое правило: имя стрима содержит имя потребителя.
  orders_stream_stg, orders_stream_audit — а не orders_stream.""")

    # Фильтр по METADATA$ACTION — не деталь стиля, а защита от задвоения.
    naive = len(before_stg)
    correct = len([r for r in before_stg if r[0] == "INSERT"])
    print(f"""
  Второй капкан — забыть фильтр по METADATA$ACTION:
    INSERT ... SELECT без фильтра  → {naive} строк в staging
    с фильтром action = 'INSERT'   → {correct} строк
  Разница в {naive - correct} строки — это один чистый DELETE плюс две
  DELETE-половины от UPDATE. Наивная загрузка вернёт в staging удалённый
  заказ и задвоит обновлённые.""")

    return {
        "audit_intact": len(after_audit) == len(before_audit),
        "stg_drained": len(after_stg) == 0,
        "naive_rows": naive,
        "filtered_rows": correct,
    }


# ═══════════════════════════════════════════════════════════
#  STEP 4 — append-only и протухание
# ═══════════════════════════════════════════════════════════

def step4_append_only_and_stale(con):
    banner("STEP 4", "APPEND_ONLY против STANDARD · протухание стрима")

    std = read_stream(con, "audit")
    app = read_stream(con, "events", append_only=True)

    print(f"  STANDARD    (audit):  {len(std)} строк — INSERT + DELETE + пары от UPDATE")
    print(f"  APPEND_ONLY (events): {len(app)} строк — только появление новых")
    print(f"""
  APPEND_ONLY пропустил {len([r for r in std if r[0] == 'DELETE' and not r[1]])} удаление и {len([r for r in std if r[1]]) // 2} обновления.
  Взамен он дешевле: не надо сопоставлять старые и новые
  micro-partitions, достаточно взять добавленные после offset.

  Когда брать APPEND_ONLY: событийные таблицы, которые никогда не
  обновляются — клики, логи, факты продаж. Когда нельзя: любые
  таблицы-состояния, где строку правят или удаляют.""")

    # ─── Stale ────────────────────────────────────────────
    # Локально это проверка возраста снимка. В Snowflake — сравнение
    # offset с DATA_RETENTION_TIME_IN_DAYS исходной таблицы.
    retention_days = 1
    offset_age_days = 3
    stale = offset_age_days > retention_days
    print(f"""
  Протухание (симуляция по возрасту offset, не по micro-partitions):
    DATA_RETENTION_TIME_IN_DAYS = {retention_days}
    стрим не читали              {offset_age_days} дня
    STALE                        {"ДА — прочитать нельзя, только пересоздать" if stale else "нет"}

  Это главная эксплуатационная боль стримов. Пайплайн падает на
  выходных, в понедельник стрим уже мёртв, изменения за выходные
  восстанавливаются только полным перезаливом. Защита — двойная:
  поднять ретенцию исходной таблицы и мониторить SHOW STREAMS
  по колонке stale_after, а не ждать ошибки при чтении.""")

    return {
        "standard_rows": len(std),
        "append_only_rows": len(app),
        "stale_simulated": stale,
    }


# ═══════════════════════════════════════════════════════════
#  STEP 5 — граф Tasks
# ═══════════════════════════════════════════════════════════

# Граф из 13_tasks.sql:
#   t_load_stg (root, SCHEDULE + WHEN)
#     ├── t_build_marts ──┐
#     └── t_audit_log ────┴── t_notify
TASK_GRAPH = {
    "t_load_stg": [],
    "t_build_marts": ["t_load_stg"],
    "t_audit_log": ["t_load_stg"],
    "t_notify": ["t_build_marts", "t_audit_log"],
}

TASK_ORDER = ["t_load_stg", "t_build_marts", "t_audit_log", "t_notify"]


def run_task_graph(tick: int, stream_has_data: bool, previous_still_running: bool,
                   failing_task: str | None):
    """Один запуск графа по расписанию. Возвращает состояние каждой задачи.

    Воспроизводит три правила Snowflake:
      1. WHEN=FALSE на корне  → корень SKIPPED, дети не запускаются вовсе
      2. предыдущий прогон не закончился → весь запуск пропущен молча
      3. родитель FAILED      → дети не запускаются
    """
    if previous_still_running:
        return [{"tick": tick, "task": t, "state": "SKIPPED",
                 "reason": "предыдущий прогон графа ещё идёт"} for t in TASK_ORDER]

    states: dict[str, str] = {}
    result = []
    for task in TASK_ORDER:
        parents = TASK_GRAPH[task]
        if not parents:
            if not stream_has_data:
                states[task] = "SKIPPED"
                reason = "WHEN: SYSTEM$STREAM_HAS_DATA = FALSE"
            elif task == failing_task:
                states[task] = "FAILED"
                reason = "ошибка в теле задачи"
            else:
                states[task] = "SUCCEEDED"
                reason = ""
        elif any(states[p] != "SUCCEEDED" for p in parents):
            blocker = next(p for p in parents if states[p] != "SUCCEEDED")
            states[task] = "SKIPPED"
            reason = f"родитель {blocker} → {states[blocker]}"
        elif task == failing_task:
            states[task] = "FAILED"
            reason = "ошибка в теле задачи"
        else:
            states[task] = "SUCCEEDED"
            reason = ""
        result.append({"tick": tick, "task": task, "state": states[task], "reason": reason})
    return result


def step5_task_graph():
    banner("STEP 5", "Граф Tasks: SKIPPED, пересечение запусков, падение")

    scenarios = [
        (1, True, False, None, "штатный прогон: в стриме есть данные"),
        (2, False, False, None, "новых данных нет"),
        (3, True, True, None, "предыдущий прогон ещё идёт"),
        (4, True, False, "t_build_marts", "падение в середине графа"),
    ]

    all_rows = []
    for tick, has_data, overlap, failing, title in scenarios:
        rows = run_task_graph(tick, has_data, overlap, failing)
        all_rows.extend(rows)
        print(f"\n  Тик {tick} — {title}")
        for r in rows:
            tail = f"  ({r['reason']})" if r["reason"] else ""
            print(f"    {r['task']:<16} {r['state']:<10}{tail}")

    succeeded = len([r for r in all_rows if r["state"] == "SUCCEEDED"])
    skipped = len([r for r in all_rows if r["state"] == "SKIPPED"])
    failed = len([r for r in all_rows if r["state"] == "FAILED"])

    print(f"""
  Итого за 4 тика: SUCCEEDED={succeeded}  SKIPPED={skipped}  FAILED={failed}

  Что здесь важно понять, а не запомнить:

  Тик 2. SKIPPED — штатное состояние, а не сбой. WHEN отработал и
  сэкономил запуск warehouse. Алерт на SKIPPED = алерт на каждую
  спокойную ночь; алертить надо на FAILED.

  Тик 3. Запуск пропущен МОЛЧА. Ошибки нет, записи о попытке — тоже.
  Задача, которая работает дольше своего интервала, тихо теряет
  прогоны, и увидеть это можно только по дыркам в task_history.
  Это ровно тот случай, когда пора смотреть на внешний оркестратор.

  Тик 4. Падение t_build_marts остановило t_notify, но t_audit_log
  успел отработать — он в другой ветке. Частичное выполнение графа:
  часть данных обновилась, часть нет. Snowflake не откатывает граф
  целиком, транзакция здесь на каждой задаче своя.""")

    return all_rows


# ═══════════════════════════════════════════════════════════
#  STEP 6 — Tasks против Dagster
# ═══════════════════════════════════════════════════════════

TRADEOFFS = [
    {
        "критерий": "Область видимости",
        "snowflake_tasks": "только объекты внутри Snowflake",
        "dagster": "Snowflake + Airbyte + API + файлы + Python",
        "вывод": "нужен шаг вне склада — Tasks сразу отпадают",
    },
    {
        "критерий": "Язык шага",
        "snowflake_tasks": "SQL, stored procedure, Snowpark",
        "dagster": "любой Python, любой subprocess",
        "вывод": "ML-скор или вызов внешнего API — не в Tasks",
    },
    {
        "критерий": "Задержка запуска",
        "snowflake_tasks": "минимум 1 минута по расписанию",
        "dagster": "сенсор от 30 секунд, event-driven",
        "вывод": "оба не про секунды",
    },
    {
        "критерий": "Наблюдаемость",
        "snowflake_tasks": "task_history: имя, state, ошибка",
        "dagster": "UI, граф ассетов, логи, партиции, backfill",
        "вывод": "при 20+ шагах task_history перестаёт помогать",
    },
    {
        "критерий": "Backfill",
        "snowflake_tasks": "нет — писать вручную циклом по датам",
        "dagster": "партиции и backfill из коробки",
        "вывод": "решающий пункт для аналитики по датам",
    },
    {
        "критерий": "Тестируемость",
        "snowflake_tasks": "только на живом аккаунте",
        "dagster": "pytest локально, как в днях 86-88",
        "вывод": "CI на Tasks построить почти нечем",
    },
    {
        "критерий": "Стоимость простоя",
        "snowflake_tasks": "0 при WHEN=FALSE, serverless посекундно",
        "dagster": "постоянно живущий daemon",
        "вывод": "редкая мелкая задача дешевле в Tasks",
    },
    {
        "критерий": "Отказ инфраструктуры",
        "snowflake_tasks": "нечему падать: часть Snowflake",
        "dagster": "свой сервис, его надо поднимать и чинить",
        "вывод": "меньше движущихся частей — меньше дежурства",
    },
]


def step6_tradeoffs():
    banner("STEP 6", "Snowflake Tasks против Dagster — где граница")

    for row in TRADEOFFS:
        print(f"\n  {row['критерий']}")
        print(f"    Tasks:   {row['snowflake_tasks']}")
        print(f"    Dagster: {row['dagster']}")
        print(f"    →        {row['вывод']}")

    print("""
  Граница проходит не по масштабу, а по границе Snowflake.

  Tasks берут на себя то, что целиком живёт внутри склада и
  описывается одним SQL: сжать стрим в staging, обновить агрегат,
  почистить старые партиции. Три-пять задач, никакого backfill.

  Всё, что пересекает границу склада — Airbyte, dbt, выгрузка в
  Lightdash — уходит в Dagster. В нашем пайплайне из дней 81-85
  так и вышло: Dagster оркестрирует, потому что Airbyte и dbt
  снаружи Snowflake, а Task для них — просто нечем вызвать.

  Гибрид — нормальная продовая конфигурация, не компромисс:
  Snowpipe и Task жмут сырьё в staging по событию, Dagster раз в
  час собирает витрины и следит за графом целиком.""")


# ═══════════════════════════════════════════════════════════
#  STEP 7 — отчёты
# ═══════════════════════════════════════════════════════════

def write_csv(path: Path, rows: list[dict]) -> Path:
    # lineterminator обязателен: диалект excel по умолчанию пишет CRLF
    # даже на Linux, и git ругается на смешанные переводы строк.
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}  ({len(rows)} строк)")
    return path


def step7_reports(mech: dict, consumers: dict, modes: dict, task_rows: list[dict]):
    banner("STEP 7", "Отчёты в reports/")

    stream_rows = [
        {"проверка": "DML-команд выполнено",
         "значение": mech["dml_ops"],
         "комментарий": "4 INSERT, 2 UPDATE, 2 DELETE"},
        {"проверка": "строк в стриме",
         "значение": mech["stream_rows"],
         "комментарий": "net change, а не журнал операций"},
        {"проверка": "чистых INSERT",
         "значение": mech["inserts"],
         "комментарий": "METADATA$ISUPDATE = FALSE"},
        {"проверка": "чистых DELETE",
         "значение": mech["deletes"],
         "комментарий": "METADATA$ISUPDATE = FALSE"},
        {"проверка": "строк от UPDATE",
         "значение": mech["update_rows"],
         "комментарий": "2 обновления = 4 строки, пары DELETE+INSERT"},
        {"проверка": "INSERT+DELETE схлопнулись",
         "значение": mech["collapsed_1012"],
         "комментарий": "заказ 1012 в стриме не появился"},
        {"проверка": "повторный SELECT стабилен",
         "значение": mech["reread_stable"],
         "комментарий": "чтение не двигает offset"},
        {"проверка": "стрим stg опустошён после DML",
         "значение": consumers["stg_drained"],
         "комментарий": "offset сдвинут коммитом"},
        {"проверка": "стрим audit не тронут",
         "значение": consumers["audit_intact"],
         "комментарий": "независимый offset второго потребителя"},
        {"проверка": "наивная загрузка без фильтра",
         "значение": consumers["naive_rows"],
         "комментарий": f"против {consumers['filtered_rows']} с фильтром по action"},
        {"проверка": "STANDARD строк",
         "значение": modes["standard_rows"],
         "комментарий": "видит INSERT/UPDATE/DELETE"},
        {"проверка": "APPEND_ONLY строк",
         "значение": modes["append_only_rows"],
         "комментарий": "видит только новые строки"},
    ]
    p1 = write_csv(REPORTS_DIR / f"day94_96_stream_semantics_{TODAY}.csv", stream_rows)
    p2 = write_csv(REPORTS_DIR / f"day94_96_task_runs_{TODAY}.csv", task_rows)
    p3 = write_csv(REPORTS_DIR / f"day94_96_tasks_vs_dagster_{TODAY}.csv", TRADEOFFS)
    return [p1, p2, p3]


# ═══════════════════════════════════════════════════════════
#  STEP 8 — на собеседовании
# ═══════════════════════════════════════════════════════════

def step8_interview():
    banner("STEP 8", "На собеседовании")
    print("""
  «Что такое Stream в Snowflake и сколько он стоит по хранению?»

    Stream — не таблица и не журнал, а offset плюс правило «покажи
    разницу между состоянием на offset и текущим». Собственных
    данных у него нет, хранение около нуля; работает он поверх того
    же механизма неизменяемых micro-partitions, что и Time Travel.
    Отсюда сразу следует ограничение: стрим живёт не дольше
    DATA_RETENTION_TIME_IN_DAYS исходной таблицы.

  «Сделали UPDATE одной строки. Что увидит стрим?»

    Две строки, а не одну: DELETE со старым значением и INSERT с
    новым, у обеих METADATA$ISUPDATE = TRUE. Отдельного значения
    UPDATE в METADATA$ACTION не существует. Практическое следствие —
    INSERT ... SELECT из стрима без фильтра по METADATA$ACTION
    задваивает обновлённые строки и возвращает удалённые.

  «Строку вставили и удалили между двумя чтениями стрима. Что в стриме?»

    Ничего. Стрим отдаёт net change, а не историю операций. Нужен
    полный журнал — это CHANGES ... APPEND_ONLY поверх Time Travel
    или отдельная аудит-таблица, но не стрим. Вопрос проверяет,
    понимаешь ли ты, что это diff, а не CDC-лог как в Debezium.

  «Два джоба читают один стрим. Что произойдёт?»

    Второй не получит ничего, и молча: ошибки не будет. Offset
    двигает не SELECT, а первая же закоммиченная транзакция с DML
    поверх стрима. Правило — один стрим на одного потребителя, имя
    стрима содержит имя потребителя. Обратная сторона того же
    правила полезна: пока транзакция не закоммичена, offset стоит,
    поэтому упавшая загрузка не теряет данные и просто повторяется.

  «Стрим протух за выходные. Что делаешь и как не допустишь снова?»

    Восстановить изменения из протухшего стрима нельзя — только
    пересоздать его и догнать данные полным сравнением с источником.
    Профилактика двойная: поднять DATA_RETENTION_TIME_IN_DAYS на
    исходной таблице с запасом на длинные выходные и мониторить
    SHOW STREAMS по колонке stale_after, а не ждать ошибки чтения.

  «Когда Snowflake Tasks, а когда Dagster?»

    Граница проходит по границе Snowflake, а не по масштабу. Всё,
    что целиком внутри склада и выражается одним SQL — сжать стрим
    в staging, обновить агрегат — дешевле и надёжнее в Tasks: там
    нечему падать и при WHEN=FALSE это стоит ноль. Как только в
    цепочке появляется Airbyte, dbt или выгрузка наружу, Tasks
    нечем это вызвать — нужен Dagster. Плюс два практических
    аргумента за оркестратор: у Tasks нет backfill по датам и их
    почти нечем покрыть тестами в CI.

  «Task не отработал, но и ошибки в task_history нет. Почему?»

    Два штатных сценария, оба дают SKIPPED. Первый — WHEN вернул
    FALSE, данных не было; это нормальная работа, а не сбой.
    Второй хуже: предыдущий прогон графа ещё шёл, а при
    ALLOW_OVERLAPPING_EXECUTION = FALSE очередной запуск
    пропускается молча. Задача, которая работает дольше своего
    интервала, тихо теряет прогоны — видно только по дыркам в
    task_history. Отсюда алерт строится на FAILED и на разрывы в
    расписании, но не на SKIPPED.

  «Чем Snowpipe отличается от COPY INTO и когда он дороже?»

    COPY INTO запускаешь ты и на своём warehouse; Snowpipe грузит
    сам по событию из облака, serverless, с задержкой в минуты —
    это не стриминг. Дороже он на мелких файлах: накладные расходы
    берутся за каждый файл, поэтому тысяча файлов по килобайту
    обойдётся дороже одного мегабайтного при том же объёме.
    Второй подвох — дедупликация: файл помнится 14 дней, перезалить
    его раньше не выйдет, а позже — данные задвоятся.
""")


def main():
    print(SEP)
    print("  lesson94_96.py — Days 94-96: Streams + Tasks")
    print(SEP)

    step1_snowflake_sql()

    con = duckdb.connect(str(SIM_DB))
    try:
        mech = step2_stream_mechanics(con)
        consumers = step3_one_consumer_per_stream(con)
        modes = step4_append_only_and_stale(con)
    finally:
        con.close()

    task_rows = step5_task_graph()
    step6_tradeoffs()
    artifacts = step7_reports(mech, consumers, modes, task_rows)
    step8_interview()

    print(SEP)
    print("  ALL DONE")
    print(SEP)
    print(f"""
Артефакты:
  snowflake_setup/12_streams.sql
  snowflake_setup/13_tasks.sql
  snowflake_setup/14_snowpipe.sql
  {artifacts[0].relative_to(PROJECT_ROOT)}
  {artifacts[1].relative_to(PROJECT_ROOT)}
  {artifacts[2].relative_to(PROJECT_ROOT)}

Что осталось несделанным честно:
  Snowflake-аккаунта нет — скрипты 12-14 написаны, но не выполнялись.
  Snowpipe локально не симулируется вообще: нет ни S3, ни очереди
  событий. Протухание стрима смоделировано по возрасту offset,
  а не по реальной ретенции micro-partitions.

Next steps:
  1. Days 97-98 — Performance Tuning (Query Profile, кеши, кластеризация)
  2. При появлении аккаунта: 12 -> 13 -> 14 в Worksheet, затем
     сверить task_history с таблицей из day94_96_task_runs
  3. Концепты в базу: /ae-concept Streams, /ae-concept Tasks, /ae-concept Snowpipe

Git:
  git add lesson94_96.py snowflake_setup/1[234]_*.sql reports/day94_96_*
  git commit -m "feat: Days 94-96 Streams + Tasks"
""")


if __name__ == "__main__":
    main()
