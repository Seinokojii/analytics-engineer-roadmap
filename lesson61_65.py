#!/usr/bin/env python3
"""
lesson61_65.py - Days 61-65: Dagster Fundamentals
Software-Defined Assets + DuckDB + Schedules + Sensors

Zapusk:
  pip install dagster dagster-webserver duckdb polars pandas
  python lesson61_65.py        # создаёт структуру проекта
  cd dagster_pipeline
  dagster dev                  # запускает UI на localhost:3000
"""

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DAGSTER_DIR  = PROJECT_ROOT / "dagster_pipeline"


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


# ── assets.py ────────────────────────────────────────────

ASSETS_PY = (
    "# dagster_pipeline/assets.py\n"
    "# Days 61-65: Software-Defined Assets\n"
    "# [[Dagster]] [[DuckDB]] [[ETL Pipeline]]\n"
    "\n"
    "import duckdb\n"
    "import pandas as pd\n"
    "import numpy as np\n"
    "from pathlib import Path\n"
    "from datetime import datetime, date, timedelta\n"
    "import random\n"
    "\n"
    "from dagster import (\n"
    "    asset, multi_asset, AssetOut, Output,\n"
    "    MetadataValue, AssetExecutionContext,\n"
    "    MaterializeResult,\n"
    ")\n"
    "\n"
    "random.seed(42)\n"
    "np.random.seed(42)\n"
    "\n"
    "DATA_DIR = Path(__file__).parent / 'data'\n"
    "DATA_DIR.mkdir(exist_ok=True)\n"
    "DB_PATH  = Path(__file__).parent / 'analytics.duckdb'\n"
    "\n"
    "\n"
    "def get_con(read_only: bool = False):\n"
    "    return duckdb.connect(str(DB_PATH), read_only=read_only)\n"
    "\n"
    "\n"
    "# ── Day 61: Первый @asset с metadata ─────────────────\n"
    "\n"
    "@asset(\n"
    "    group_name='ingestion',\n"
    "    kinds={'python', 'csv'},\n"
    "    description='Генерирует и загружает raw_orders CSV',\n"
    ")\n"
    "def raw_orders(context: AssetExecutionContext) -> Output:\n"
    "    n = 1000\n"
    "    cities  = ['MOSCOW', 'SPB', 'KAZAN', 'NOVOSIBIRSK', 'YEKATERINBURG']\n"
    "    df = pd.DataFrame({\n"
    "        'order_id':   range(1, n + 1),\n"
    "        'user_id':    np.random.randint(1, 101, n),\n"
    "        'amount':     np.round(np.random.uniform(10, 5000, n), 2),\n"
    "        'status':     np.random.choice(['completed', 'pending', 'cancelled'], n,\n"
    "                                       p=[0.7, 0.2, 0.1]),\n"
    "        'city':       np.random.choice(cities, n),\n"
    "        'order_date': [\n"
    "            date(2024, 1, 1) + timedelta(days=random.randint(0, 364))\n"
    "            for _ in range(n)\n"
    "        ],\n"
    "    })\n"
    "\n"
    "    csv_path = DATA_DIR / 'raw_orders.csv'\n"
    "    df.to_csv(csv_path, index=False)\n"
    "\n"
    "    context.log.info(f'Generated {n} orders -> {csv_path}')\n"
    "\n"
    "    return Output(\n"
    "        value=df,\n"
    "        metadata={\n"
    "            'row_count':  len(df),\n"
    "            'file_size':  csv_path.stat().st_size,\n"
    "            'timestamp':  str(datetime.now()),\n"
    "            'cities':     MetadataValue.json(list(df['city'].unique())),\n"
    "            'preview':    MetadataValue.md(df.head(3).to_markdown()),\n"
    "        }\n"
    "    )\n"
    "\n"
    "\n"
    "@asset(\n"
    "    group_name='ingestion',\n"
    "    kinds={'python', 'csv'},\n"
    "    description='Генерирует raw_users CSV',\n"
    ")\n"
    "def raw_users(context: AssetExecutionContext) -> Output:\n"
    "    channels = ['organic', 'paid', 'referral', 'social']\n"
    "    cities   = ['MOSCOW', 'SPB', 'KAZAN', 'NOVOSIBIRSK', 'YEKATERINBURG']\n"
    "    n = 100\n"
    "    df = pd.DataFrame({\n"
    "        'user_id':   range(1, n + 1),\n"
    "        'email':     [f'user{i}@example.com' for i in range(1, n + 1)],\n"
    "        'city':      np.random.choice(cities, n),\n"
    "        'channel':   np.random.choice(channels, n, p=[0.4, 0.3, 0.2, 0.1]),\n"
    "        'created_at': [\n"
    "            date(2023, 1, 1) + timedelta(days=random.randint(0, 364))\n"
    "            for _ in range(n)\n"
    "        ],\n"
    "    })\n"
    "\n"
    "    csv_path = DATA_DIR / 'raw_users.csv'\n"
    "    df.to_csv(csv_path, index=False)\n"
    "\n"
    "    return Output(\n"
    "        value=df,\n"
    "        metadata={\n"
    "            'row_count': len(df),\n"
    "            'file_size': csv_path.stat().st_size,\n"
    "            'timestamp': str(datetime.now()),\n"
    "        }\n"
    "    )\n"
    "\n"
    "\n"
    "# ── Day 63: Deps chain: raw -> stg -> fct ────────────\n"
    "\n"
    "@asset(\n"
    "    deps=['raw_orders'],\n"
    "    group_name='staging',\n"
    "    kinds={'duckdb'},\n"
    "    description='Очищает raw_orders: только completed, amount > 0',\n"
    ")\n"
    "def stg_orders(context: AssetExecutionContext) -> Output:\n"
    "    con = get_con()\n"
    "    con.execute(\"\"\"\n"
    "        CREATE OR REPLACE TABLE stg_orders AS\n"
    "        SELECT\n"
    "            order_id,\n"
    "            user_id,\n"
    "            ROUND(amount, 2) AS amount,\n"
    "            city,\n"
    "            order_date::DATE AS order_date\n"
    "        FROM read_csv_auto('{csv}')\n"
    "        WHERE status = 'completed'\n"
    "          AND amount > 0\n"
    "    \"\"\".replace('{csv}', str(DATA_DIR / 'raw_orders.csv')))\n"
    "\n"
    "    cnt = con.execute('SELECT COUNT(*) FROM stg_orders').fetchone()[0]\n"
    "    con.close()\n"
    "\n"
    "    context.log.info(f'stg_orders: {cnt} rows (completed only)')\n"
    "\n"
    "    return Output(\n"
    "        value=cnt,\n"
    "        metadata={\n"
    "            'row_count': cnt,\n"
    "            'filter':    'status=completed AND amount>0',\n"
    "            'timestamp': str(datetime.now()),\n"
    "        }\n"
    "    )\n"
    "\n"
    "\n"
    "@asset(\n"
    "    deps=['raw_users'],\n"
    "    group_name='staging',\n"
    "    kinds={'duckdb'},\n"
    "    description='Очищает raw_users: LOWER email, UPPER city',\n"
    ")\n"
    "def stg_users(context: AssetExecutionContext) -> Output:\n"
    "    con = get_con()\n"
    "    con.execute(\"\"\"\n"
    "        CREATE OR REPLACE TABLE stg_users AS\n"
    "        SELECT\n"
    "            user_id,\n"
    "            LOWER(TRIM(email))  AS email,\n"
    "            UPPER(city)         AS city,\n"
    "            channel,\n"
    "            created_at::DATE    AS created_at\n"
    "        FROM read_csv_auto('{csv}')\n"
    "        WHERE email IS NOT NULL\n"
    "    \"\"\".replace('{csv}', str(DATA_DIR / 'raw_users.csv')))\n"
    "\n"
    "    cnt = con.execute('SELECT COUNT(*) FROM stg_users').fetchone()[0]\n"
    "    con.close()\n"
    "\n"
    "    return Output(value=cnt, metadata={'row_count': cnt})\n"
    "\n"
    "\n"
    "@asset(\n"
    "    deps=['stg_orders', 'stg_users'],\n"
    "    group_name='marts',\n"
    "    kinds={'duckdb'},\n"
    "    description='Fact table: orders JOIN users, biznes-metriki',\n"
    ")\n"
    "def fct_orders(context: AssetExecutionContext) -> Output:\n"
    "    con = get_con()\n"
    "    con.execute(\"\"\"\n"
    "        CREATE OR REPLACE TABLE fct_orders AS\n"
    "        SELECT\n"
    "            o.order_id,\n"
    "            o.user_id,\n"
    "            u.email,\n"
    "            o.city,\n"
    "            u.channel,\n"
    "            o.amount,\n"
    "            o.order_date\n"
    "        FROM stg_orders o\n"
    "        LEFT JOIN stg_users u ON o.user_id = u.user_id\n"
    "    \"\"\")\n"
    "\n"
    "    stats = con.execute(\"\"\"\n"
    "        SELECT\n"
    "            COUNT(*)          AS row_count,\n"
    "            ROUND(SUM(amount),2)  AS total_revenue,\n"
    "            ROUND(AVG(amount),2)  AS avg_order_value\n"
    "        FROM fct_orders\n"
    "    \"\"\").fetchone()\n"
    "    con.close()\n"
    "\n"
    "    context.log.info(f'fct_orders: {stats[0]} rows | revenue={stats[1]}')\n"
    "\n"
    "    return Output(\n"
    "        value=stats[0],\n"
    "        metadata={\n"
    "            'row_count':          stats[0],\n"
    "            'total_revenue':      stats[1],\n"
    "            'avg_order_value':    stats[2],\n"
    "            'timestamp':          str(datetime.now()),\n"
    "        }\n"
    "    )\n"
    "\n"
    "\n"
    "# ── Day 63: @multi_asset ──────────────────────────────\n"
    "\n"
    "@multi_asset(\n"
    "    deps=['stg_orders', 'stg_users'],\n"
    "    outs={\n"
    "        'dim_customers': AssetOut(\n"
    "            group_name='marts',\n"
    "            kinds={'duckdb'},\n"
    "            description='Dimension: клиенты с агрегатами',\n"
    "        ),\n"
    "        'dim_dates': AssetOut(\n"
    "            group_name='marts',\n"
    "            kinds={'duckdb'},\n"
    "            description='Date dimension: 2023-2025',\n"
    "        ),\n"
    "    }\n"
    ")\n"
    "def build_dimensions(context: AssetExecutionContext):\n"
    "    con = get_con()\n"
    "\n"
    "    # dim_customers\n"
    "    con.execute(\"\"\"\n"
    "        CREATE OR REPLACE TABLE dim_customers AS\n"
    "        SELECT\n"
    "            u.user_id,\n"
    "            u.email,\n"
    "            u.city,\n"
    "            u.channel,\n"
    "            COUNT(o.order_id)       AS total_orders,\n"
    "            ROUND(SUM(o.amount),2)  AS total_spent,\n"
    "            ROUND(AVG(o.amount),2)  AS avg_order_value,\n"
    "            MAX(o.order_date)       AS last_order_date\n"
    "        FROM stg_users u\n"
    "        LEFT JOIN stg_orders o ON u.user_id = o.user_id\n"
    "        GROUP BY u.user_id, u.email, u.city, u.channel\n"
    "    \"\"\")\n"
    "\n"
    "    # dim_dates\n"
    "    con.execute(\"\"\"\n"
    "        CREATE OR REPLACE TABLE dim_dates AS\n"
    "        SELECT\n"
    "            gs::DATE                    AS date_day,\n"
    "            EXTRACT(YEAR  FROM gs::DATE) AS year,\n"
    "            EXTRACT(MONTH FROM gs::DATE) AS month,\n"
    "            EXTRACT(DOW   FROM gs::DATE) AS day_of_week,\n"
    "            CASE EXTRACT(DOW FROM gs::DATE)\n"
    "                WHEN 0 THEN 'Sunday'\n"
    "                WHEN 1 THEN 'Monday'\n"
    "                WHEN 2 THEN 'Tuesday'\n"
    "                WHEN 3 THEN 'Wednesday'\n"
    "                WHEN 4 THEN 'Thursday'\n"
    "                WHEN 5 THEN 'Friday'\n"
    "                WHEN 6 THEN 'Saturday'\n"
    "            END                          AS day_name\n"
    "        FROM GENERATE_SERIES(\n"
    "            DATE '2023-01-01',\n"
    "            DATE '2025-12-31',\n"
    "            INTERVAL '1 day'\n"
    "        ) t(gs)\n"
    "    \"\"\")\n"
    "\n"
    "    c_cnt = con.execute('SELECT COUNT(*) FROM dim_customers').fetchone()[0]\n"
    "    d_cnt = con.execute('SELECT COUNT(*) FROM dim_dates').fetchone()[0]\n"
    "    con.close()\n"
    "\n"
    "    context.log.info(f'dim_customers={c_cnt} | dim_dates={d_cnt}')\n"
    "\n"
    "    yield Output(c_cnt, output_name='dim_customers',\n"
    "                 metadata={'row_count': c_cnt})\n"
    "    yield Output(d_cnt, output_name='dim_dates',\n"
    "                 metadata={'row_count': d_cnt})\n"
)

# ── schedules_sensors.py ─────────────────────────────────

SCHEDULES_SENSORS_PY = (
    "# dagster_pipeline/schedules_sensors.py\n"
    "# Day 65: @schedule + @sensor + RunConfig\n"
    "# [[Dagster]] [[Scheduling]]\n"
    "\n"
    "from dagster import (\n"
    "    define_asset_job, ScheduleDefinition,\n"
    "    sensor, RunRequest, SensorEvaluationContext,\n"
    "    SkipReason,\n"
    ")\n"
    "from pathlib import Path\n"
    "import json\n"
    "\n"
    "DATA_DIR = Path(__file__).parent / 'data'\n"
    "INBOX    = Path(__file__).parent / 'inbox'\n"
    "INBOX.mkdir(exist_ok=True)\n"
    "\n"
    "# ── Jobs ─────────────────────────────────────────────\n"
    "\n"
    "# Запускает весь pipeline: raw -> stg -> fct -> dims\n"
    "full_pipeline_job = define_asset_job(\n"
    "    name='full_pipeline_job',\n"
    "    selection=[\n"
    "        'raw_orders', 'raw_users',\n"
    "        'stg_orders', 'stg_users',\n"
    "        'fct_orders',\n"
    "        'build_dimensions',\n"
    "    ],\n"
    ")\n"
    "\n"
    "# Только ingestion\n"
    "ingestion_job = define_asset_job(\n"
    "    name='ingestion_job',\n"
    "    selection=['raw_orders', 'raw_users'],\n"
    ")\n"
    "\n"
    "# ── Schedules ────────────────────────────────────────\n"
    "\n"
    "# Каждое утро в 6:00 UTC\n"
    "daily_analytics_schedule = ScheduleDefinition(\n"
    "    name='daily_analytics_schedule',\n"
    "    job=full_pipeline_job,\n"
    "    cron_schedule='0 6 * * *',\n"
    "    description='Ежедневный ETL pipeline в 6:00 UTC',\n"
    ")\n"
    "\n"
    "# Каждый понедельник\n"
    "weekly_refresh_schedule = ScheduleDefinition(\n"
    "    name='weekly_refresh_schedule',\n"
    "    job=full_pipeline_job,\n"
    "    cron_schedule='0 4 * * 1',\n"
    "    description='Еженедельный полный refresh по понедельникам в 4:00 UTC',\n"
    ")\n"
    "\n"
    "# ── Sensor ───────────────────────────────────────────\n"
    "\n"
    "@sensor(\n"
    "    job=ingestion_job,\n"
    "    description='Запускает ingestion когда в inbox/ появляется новый CSV',\n"
    "    minimum_interval_seconds=30,\n"
    ")\n"
    "def new_csv_sensor(context: SensorEvaluationContext):\n"
    "    # Читаем курсор (последний обработанный файл)\n"
    "    cursor = context.cursor or ''\n"
    "\n"
    "    new_files = sorted(\n"
    "        f for f in INBOX.glob('*.csv')\n"
    "        if f.name > cursor\n"
    "    )\n"
    "\n"
    "    if not new_files:\n"
    "        yield SkipReason(f'No new CSV files in {INBOX}')\n"
    "        return\n"
    "\n"
    "    for csv_file in new_files:\n"
    "        context.log.info(f'New file detected: {csv_file.name}')\n"
    "        yield RunRequest(\n"
    "            run_key=csv_file.name,\n"
    "            run_config={\n"
    "                'ops': {\n"
    "                    'raw_orders': {'config': {'source_file': str(csv_file)}}\n"
    "                }\n"
    "            },\n"
    "            tags={'source_file': csv_file.name},\n"
    "        )\n"
    "\n"
    "    # Обновляем cursor\n"
    "    context.update_cursor(new_files[-1].name)\n"
)

# ── asset_checks.py ──────────────────────────────────────

ASSET_CHECKS_PY = (
    "# dagster_pipeline/asset_checks.py\n"
    "# Quality checks для assets -- аналог dbt test\n"
    "# [[Dagster]] [[Data Quality]]\n"
    "\n"
    "import duckdb\n"
    "from pathlib import Path\n"
    "from dagster import asset_check, AssetCheckResult, AssetCheckSeverity\n"
    "\n"
    "DB_PATH = Path(__file__).parent / 'analytics.duckdb'\n"
    "\n"
    "\n"
    "def get_con():\n"
    "    return duckdb.connect(str(DB_PATH), read_only=True)\n"
    "\n"
    "\n"
    "@asset_check(asset='fct_orders', description='Нет заказов с отрицательной суммой')\n"
    "def check_no_negative_amount():\n"
    "    con = get_con()\n"
    "    bad = con.execute('SELECT COUNT(*) FROM fct_orders WHERE amount < 0').fetchone()[0]\n"
    "    con.close()\n"
    "    return AssetCheckResult(\n"
    "        passed=bad == 0,\n"
    "        metadata={'negative_rows': bad},\n"
    "        severity=AssetCheckSeverity.ERROR,\n"
    "    )\n"
    "\n"
    "\n"
    "@asset_check(asset='fct_orders', description='Все order_id уникальные')\n"
    "def check_unique_order_ids():\n"
    "    con = get_con()\n"
    "    total = con.execute('SELECT COUNT(*) FROM fct_orders').fetchone()[0]\n"
    "    uniq  = con.execute('SELECT COUNT(DISTINCT order_id) FROM fct_orders').fetchone()[0]\n"
    "    con.close()\n"
    "    return AssetCheckResult(\n"
    "        passed=total == uniq,\n"
    "        metadata={'total': total, 'unique': uniq, 'duplicates': total - uniq},\n"
    "    )\n"
    "\n"
    "\n"
    "@asset_check(asset='stg_orders', description='Net NULL v amount')\n"
    "def check_no_null_amount():\n"
    "    con = get_con()\n"
    "    nulls = con.execute('SELECT COUNT(*) FROM stg_orders WHERE amount IS NULL').fetchone()[0]\n"
    "    con.close()\n"
    "    return AssetCheckResult(passed=nulls == 0, metadata={'null_rows': nulls})\n"
)

# ── definitions.py ───────────────────────────────────────

DEFINITIONS_PY = (
    "# dagster_pipeline/definitions.py\n"
    "# Главный entry point для Dagster\n"
    "# 'dagster dev' читает этот файл\n"
    "\n"
    "from dagster import Definitions\n"
    "from assets import (\n"
    "    raw_orders, raw_users,\n"
    "    stg_orders, stg_users,\n"
    "    fct_orders, build_dimensions,\n"
    ")\n"
    "from schedules_sensors import (\n"
    "    full_pipeline_job, ingestion_job,\n"
    "    daily_analytics_schedule, weekly_refresh_schedule,\n"
    "    new_csv_sensor,\n"
    ")\n"
    "from asset_checks import (\n"
    "    check_no_negative_amount,\n"
    "    check_unique_order_ids,\n"
    "    check_no_null_amount,\n"
    ")\n"
    "\n"
    "defs = Definitions(\n"
    "    assets=[\n"
    "        raw_orders, raw_users,\n"
    "        stg_orders, stg_users,\n"
    "        fct_orders, build_dimensions,\n"
    "    ],\n"
    "    jobs=[\n"
    "        full_pipeline_job,\n"
    "        ingestion_job,\n"
    "    ],\n"
    "    schedules=[\n"
    "        daily_analytics_schedule,\n"
    "        weekly_refresh_schedule,\n"
    "    ],\n"
    "    sensors=[\n"
    "        new_csv_sensor,\n"
    "    ],\n"
    "    asset_checks=[\n"
    "        check_no_negative_amount,\n"
    "        check_unique_order_ids,\n"
    "        check_no_null_amount,\n"
    "    ],\n"
    ")\n"
)

# ── pyproject.toml ───────────────────────────────────────

PYPROJECT_TOML = """\
[tool.dagster]
module_name = "definitions"
"""


def main():
    print("=" * 55)
    print("  Days 61-65: Dagster Fundamentals Setup")
    print("=" * 55)

    print("\n[1/5] Creating dagster_pipeline/ structure...")
    write_utf8(DAGSTER_DIR / "assets.py",             ASSETS_PY)
    write_utf8(DAGSTER_DIR / "schedules_sensors.py",  SCHEDULES_SENSORS_PY)
    write_utf8(DAGSTER_DIR / "asset_checks.py",       ASSET_CHECKS_PY)
    write_utf8(DAGSTER_DIR / "definitions.py",        DEFINITIONS_PY)
    write_utf8(DAGSTER_DIR / "pyproject.toml",        PYPROJECT_TOML)

    print("\n[2/5] Installing Dagster...")
    r = subprocess.run(
        "pip install dagster dagster-webserver duckdb pandas numpy --quiet",
        shell=True, capture_output=True, text=True
    )
    if r.returncode == 0:
        print("  OK dagster installed")
    else:
        print(f"  WARNING: {r.stderr[-200:]}")

    print("\n[3/5] Validating Python syntax...")
    import py_compile
    ok = True
    for f in ["assets.py", "schedules_sensors.py",
              "asset_checks.py", "definitions.py"]:
        try:
            py_compile.compile(str(DAGSTER_DIR / f), doraise=True)
            print(f"  OK {f}")
        except py_compile.PyCompileError as e:
            print(f"  ERROR {f}: {e}")
            ok = False

    print("\n[4/5] Creating inbox/ for sensor demo...")
    inbox = DAGSTER_DIR / "inbox"
    inbox.mkdir(exist_ok=True)
    # Kладём тестовый CSV чтобы sensor сработал
    import pandas as pd
    pd.DataFrame({
        "order_id": [9001, 9002],
        "amount":   [150.0, 320.0],
    }).to_csv(inbox / "new_orders_2026_04_01.csv", index=False)
    print("  OK inbox/new_orders_2026_04_01.csv (sensor demo file)")

    print("\n" + "=" * 55)
    if ok:
        print("  ALL DONE!")
    else:
        print("  WARNING: Fix errors above")
    print("=" * 55)
    print("""
Следующие шаги:
  cd dagster_pipeline
  dagster dev

Otkroy v brauzere:
  http://localhost:3000           <- Asset catalog
  http://localhost:3000/assets    <- Все assets с lineage
  http://localhost:3000/schedules <- Расписания

Запуск всех assets через UI:
  Assets -> Materialize All

Проверить sensor:
  Sensors -> new_csv_sensor -> Evaluate

Git:
  git add dagster_pipeline/ lesson61_65.py
  git commit -m "feat: Days 61-65 Dagster SDA + DuckDB pipeline"
  git push origin main
""")


if __name__ == "__main__":
    main()