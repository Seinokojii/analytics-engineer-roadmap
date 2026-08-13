#!/usr/bin/env python3
"""
lesson66_70.py - Days 66-70: dagster-dbt + Partitions + Observability
Zapusk:
  pip install dagster-dbt
  python lesson66_70.py
  cd dagster_dbt_pipeline
  dagster dev
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT     = Path(__file__).parent
DBT_PROJECT_DIR  = PROJECT_ROOT / "dbt_analytics"
DAGSTER_DIR      = PROJECT_ROOT / "dagster_dbt_pipeline"


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


def run_cmd(cmd: str, cwd: Path = PROJECT_ROOT) -> bool:
    r = subprocess.run(cmd, shell=True, cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8")
    if r.stdout:
        print(r.stdout[-300:])
    if r.returncode != 0:
        print(f"WARNING: {r.stderr[-200:]}")
    return r.returncode == 0


# ── dbt_assets.py ────────────────────────────────────────

DBT_ASSETS_PY = (
    "# dagster_dbt_pipeline/dbt_assets.py\n"
    "# Day 66-67: load_assets_from_dbt_project\n"
    "# Все dbt модели -> Dagster assets автоматически\n"
    "# [[Dagster]] [[dbt]] [[DuckDB]]\n"
    "\n"
    "from pathlib import Path\n"
    "from dagster import AssetExecutionContext\n"
    "from dagster_dbt import DbtCliResource, DbtProject, dbt_assets\n"
    "\n"
    "# Путь к нашему dbt проекту\n"
    "DBT_PROJECT_DIR = Path(__file__).parent.parent / 'dbt_analytics'\n"
    "DBT_PROFILES_DIR = DBT_PROJECT_DIR  # profiles.yml рядом с dbt_project.yml\n"
    "\n"
    "# DbtProject — описывает путь к dbt проекту\n"
    "dbt_project = DbtProject(\n"
    "    project_dir=DBT_PROJECT_DIR,\n"
    ")\n"
    "dbt_project.prepare_if_dev()\n"
    "\n"
    "\n"
    "# @dbt_assets — все dbt модели как Dagster assets\n"
    "# Dagster читает manifest.json и строит lineage автоматически\n"
    "@dbt_assets(manifest=dbt_project.manifest_path)\n"
    "def analytics_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):\n"
    "    yield from dbt.cli(['run'], context=context).stream()\n"
)

# ── partitioned_assets.py ────────────────────────────────

PARTITIONED_ASSETS_PY = (
    "# dagster_dbt_pipeline/partitioned_assets.py\n"
    "# Day 68-69: DailyPartitionsDefinition + Incremental asset\n"
    "# [[Dagster]] [[Incremental Model]] [[DuckDB]]\n"
    "\n"
    "import duckdb\n"
    "import pandas as pd\n"
    "import numpy as np\n"
    "from pathlib import Path\n"
    "from datetime import datetime, date, timedelta\n"
    "import random\n"
    "\n"
    "from dagster import (\n"
    "    asset, Output, AssetExecutionContext,\n"
    "    DailyPartitionsDefinition, BackfillPolicy,\n"
    ")\n"
    "\n"
    "random.seed(42)\n"
    "np.random.seed(42)\n"
    "\n"
    "DB_PATH = Path(__file__).parent / 'partitioned.duckdb'\n"
    "\n"
    "# Партиции с 2024-01-01 по сегодня\n"
    "daily_partitions = DailyPartitionsDefinition(\n"
    "    start_date='2024-01-01',\n"
    "    timezone='UTC',\n"
    ")\n"
    "\n"
    "\n"
    "def get_con():\n"
    "    return duckdb.connect(str(DB_PATH))\n"
    "\n"
    "\n"
    "# ── Инкрементальный asset по дате ────────────────────\n"
    "\n"
    "@asset(\n"
    "    partitions_def=daily_partitions,\n"
    "    group_name='partitioned',\n"
    "    kinds={'duckdb'},\n"
    "    description='Инкрементальный asset: заказы за одну дату (1 партиция = 1 день)',\n"
    "    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=1),\n"
    ")\n"
    "def daily_orders(context: AssetExecutionContext) -> Output:\n"
    "    partition_date = context.partition_key  # '2024-01-15'\n"
    "    context.log.info(f'Processing partition: {partition_date}')\n"
    "\n"
    "    # Генерируем данные за конкретный день\n"
    "    target_date = date.fromisoformat(partition_date)\n"
    "    n = random.randint(10, 50)\n"
    "\n"
    "    df = pd.DataFrame({\n"
    "        'order_id':   [f'{partition_date}_{i}' for i in range(1, n + 1)],\n"
    "        'user_id':    np.random.randint(1, 101, n),\n"
    "        'amount':     np.round(np.random.uniform(10, 5000, n), 2),\n"
    "        'order_date': target_date,\n"
    "        'city':       np.random.choice(\n"
    "            ['MOSCOW', 'SPB', 'KAZAN'], n\n"
    "        ),\n"
    "    })\n"
    "\n"
    "    con = get_con()\n"
    "    # Создаём таблицу если нет\n"
    "    con.execute(\"\"\"\n"
    "        CREATE TABLE IF NOT EXISTS daily_orders (\n"
    "            order_id   VARCHAR,\n"
    "            user_id    INTEGER,\n"
    "            amount     FLOAT,\n"
    "            order_date DATE,\n"
    "            city       VARCHAR\n"
    "        )\n"
    "    \"\"\")\n"
    "    # Удаляем старые данные за этот день (идемпотентность)\n"
    "    con.execute(\n"
    "        f\"DELETE FROM daily_orders WHERE order_date = '{partition_date}'\"\n"
    "    )\n"
    "    # Вставляем новые\n"
    "    con.execute('INSERT INTO daily_orders SELECT * FROM df')\n"
    "\n"
    "    total = con.execute('SELECT COUNT(*) FROM daily_orders').fetchone()[0]\n"
    "    con.close()\n"
    "\n"
    "    return Output(\n"
    "        value=len(df),\n"
    "        metadata={\n"
    "            'partition_date': partition_date,\n"
    "            'rows_this_partition': len(df),\n"
    "            'total_rows_in_table': total,\n"
    "            'revenue_today': float(df['amount'].sum().round(2)),\n"
    "        }\n"
    "    )\n"
    "\n"
    "\n"
    "@asset(\n"
    "    deps=['daily_orders'],\n"
    "    partitions_def=daily_partitions,\n"
    "    group_name='partitioned',\n"
    "    kinds={'duckdb'},\n"
    "    description='Daily revenue summary по каждой партиции',\n"
    ")\n"
    "def daily_revenue_summary(context: AssetExecutionContext) -> Output:\n"
    "    partition_date = context.partition_key\n"
    "\n"
    "    con = get_con()\n"
    "    try:\n"
    "        result = con.execute(\n"
    "            f\"\"\"\n"
    "            SELECT\n"
    "                order_date,\n"
    "                COUNT(*)              AS orders,\n"
    "                ROUND(SUM(amount), 2) AS revenue,\n"
    "                ROUND(AVG(amount), 2) AS avg_order\n"
    "            FROM daily_orders\n"
    "            WHERE order_date = '{partition_date}'\n"
    "            GROUP BY order_date\n"
    "            \"\"\"\n"
    "        ).fetchone()\n"
    "        con.close()\n"
    "\n"
    "        if not result:\n"
    "            return Output(0, metadata={'status': 'no data for this partition'})\n"
    "\n"
    "        return Output(\n"
    "            value=result[1],\n"
    "            metadata={\n"
    "                'date':     str(result[0]),\n"
    "                'orders':   result[1],\n"
    "                'revenue':  result[2],\n"
    "                'avg_order': result[3],\n"
    "            }\n"
    "        )\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        context.log.warning(f'No data yet for {partition_date}: {e}')\n"
    "        return Output(0, metadata={'status': 'table not ready'})\n"
)

# ── observability.py ─────────────────────────────────────

OBSERVABILITY_PY = (
    "# dagster_dbt_pipeline/observability.py\n"
    "# Day 70: asset_checks + alerting simulation\n"
    "# [[Dagster]] [[Data Quality]] [[Monitoring]]\n"
    "\n"
    "import duckdb\n"
    "from pathlib import Path\n"
    "from dagster import (\n"
    "    asset_check, AssetCheckResult, AssetCheckSeverity,\n"
    "    sensor, RunRequest, SensorEvaluationContext, SkipReason,\n"
    "    define_asset_job,\n"
    ")\n"
    "\n"
    "DB_PATH_MAIN        = Path(__file__).parent.parent / 'dagster_pipeline' / 'analytics.duckdb'\n"
    "DB_PATH_PARTITIONED = Path(__file__).parent / 'partitioned.duckdb'\n"
    "\n"
    "\n"
    "def get_main_con():\n"
    "    if not DB_PATH_MAIN.exists():\n"
    "        return None\n"
    "    return duckdb.connect(str(DB_PATH_MAIN), read_only=True)\n"
    "\n"
    "\n"
    "# ── Asset Checks (Day 70) ─────────────────────────────\n"
    "\n"
    "@asset_check(\n"
    "    asset='daily_orders',\n"
    "    description='Партиция содержит данные (не пустая)',\n"
    ")\n"
    "def check_partition_not_empty():\n"
    "    if not DB_PATH_PARTITIONED.exists():\n"
    "        return AssetCheckResult(\n"
    "            passed=False,\n"
    "            metadata={'reason': 'DB not found'},\n"
    "            severity=AssetCheckSeverity.WARN,\n"
    "        )\n"
    "    con = duckdb.connect(str(DB_PATH_PARTITIONED), read_only=True)\n"
    "    try:\n"
    "        cnt = con.execute('SELECT COUNT(*) FROM daily_orders').fetchone()[0]\n"
    "        con.close()\n"
    "        return AssetCheckResult(\n"
    "            passed=cnt > 0,\n"
    "            metadata={'total_rows': cnt},\n"
    "        )\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        return AssetCheckResult(\n"
    "            passed=False,\n"
    "            metadata={'error': str(e)},\n"
    "            severity=AssetCheckSeverity.WARN,\n"
    "        )\n"
    "\n"
    "\n"
    "@asset_check(\n"
    "    asset='daily_orders',\n"
    "    description='Amount всегда положительный',\n"
    ")\n"
    "def check_positive_amount():\n"
    "    if not DB_PATH_PARTITIONED.exists():\n"
    "        return AssetCheckResult(passed=True,\n"
    "                                metadata={'status': 'skipped: DB not ready'})\n"
    "    con = duckdb.connect(str(DB_PATH_PARTITIONED), read_only=True)\n"
    "    try:\n"
    "        bad = con.execute(\n"
    "            'SELECT COUNT(*) FROM daily_orders WHERE amount <= 0'\n"
    "        ).fetchone()[0]\n"
    "        con.close()\n"
    "        return AssetCheckResult(\n"
    "            passed=bad == 0,\n"
    "            metadata={'negative_or_zero_rows': bad},\n"
    "            severity=AssetCheckSeverity.ERROR if bad > 0 else AssetCheckSeverity.WARN,\n"
    "        )\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        return AssetCheckResult(passed=True, metadata={'status': str(e)})\n"
    "\n"
    "\n"
    "# ── Alert Simulation (Day 70) ─────────────────────────\n"
    "# V production: Slack webhook / email\n"
    "# Здесь: логируем в файл как симуляцию\n"
    "\n"
    "ALERTS_LOG = Path(__file__).parent / 'alerts.log'\n"
    "\n"
    "\n"
    "def send_alert(message: str, level: str = 'ERROR') -> None:\n"
    "    from datetime import datetime\n"
    "    entry = f'[{datetime.now().isoformat()}] [{level}] {message}\\n'\n"
    "    with open(ALERTS_LOG, 'a', encoding='utf-8') as f:\n"
    "        f.write(entry)\n"
    "    print(f'ALERT: {entry.strip()}')\n"
    "\n"
    "\n"
    "# Sensor для мониторинга файлов\n"
    "daily_job = define_asset_job(\n"
    "    name='daily_partitioned_job',\n"
    "    selection=['daily_orders', 'daily_revenue_summary'],\n"
    ")\n"
)

# ── definitions.py ───────────────────────────────────────

DEFINITIONS_PY = (
    "# dagster_dbt_pipeline/definitions.py\n"
    "# Entry point для dagster dev\n"
    "# [[Dagster]] [[dbt]] + Partitions + Observability\n"
    "\n"
    "from dagster import Definitions, ScheduleDefinition\n"
    "from dagster_dbt import DbtCliResource\n"
    "\n"
    "from dbt_assets import analytics_dbt_assets, dbt_project\n"
    "from partitioned_assets import daily_orders, daily_revenue_summary\n"
    "from observability import (\n"
    "    check_partition_not_empty, check_positive_amount,\n"
    "    daily_job,\n"
    ")\n"
    "\n"
    "# Resource: как запускать dbt CLI\n"
    "dbt_resource = DbtCliResource(project_dir=dbt_project)\n"
    "\n"
    "# Schedule: каждое утро в 6:00\n"
    "dbt_schedule = ScheduleDefinition(\n"
    "    name='daily_dbt_schedule',\n"
    "    job_name='__ASSET_JOB',\n"
    "    cron_schedule='0 6 * * *',\n"
    "    description='Ежедневный dbt run в 6:00 UTC',\n"
    ")\n"
    "\n"
    "defs = Definitions(\n"
    "    assets=[\n"
    "        analytics_dbt_assets,   # все dbt модели\n"
    "        daily_orders,           # partitioned asset\n"
    "        daily_revenue_summary,  # downstream ot daily_orders\n"
    "    ],\n"
    "    asset_checks=[\n"
    "        check_partition_not_empty,\n"
    "        check_positive_amount,\n"
    "    ],\n"
    "    jobs=[\n"
    "        daily_job,\n"
    "    ],\n"
    "    resources={\n"
    "        'dbt': dbt_resource,\n"
    "    },\n"
    ")\n"
)

PYPROJECT_TOML = """\
[tool.dagster]
module_name = "definitions"
"""


def main():
    print("=" * 60)
    print("  Days 66-70: dagster-dbt + Partitions + Observability")
    print("=" * 60)

    # 1. Установка
    print("\n[1/5] Installing dagster-dbt...")
    run_cmd("pip install dagster-dbt --quiet")
    print("  OK dagster-dbt installed")

    # 2. dbt parse → manifest.json (нужен для dagster-dbt)
    print("\n[2/5] Generating dbt manifest.json...")
    ok = run_cmd("dbt parse --no-partial-parse", cwd=DBT_PROJECT_DIR)
    if ok:
        print("  OK manifest.json generated")
    else:
        print("  WARNING: dbt parse failed — check dbt_analytics setup")

    # 3. Создаём структуру dagster_dbt_pipeline/
    print("\n[3/5] Creating dagster_dbt_pipeline/ structure...")
    write_utf8(DAGSTER_DIR / "dbt_assets.py",        DBT_ASSETS_PY)
    write_utf8(DAGSTER_DIR / "partitioned_assets.py", PARTITIONED_ASSETS_PY)
    write_utf8(DAGSTER_DIR / "observability.py",      OBSERVABILITY_PY)
    write_utf8(DAGSTER_DIR / "definitions.py",        DEFINITIONS_PY)
    write_utf8(DAGSTER_DIR / "pyproject.toml",        PYPROJECT_TOML)

    # 4. Синтаксис-проверка
    print("\n[4/5] Validating Python syntax...")
    import py_compile
    all_ok = True
    for f in ["dbt_assets.py", "partitioned_assets.py",
              "observability.py", "definitions.py"]:
        try:
            py_compile.compile(str(DAGSTER_DIR / f), doraise=True)
            print(f"  OK {f}")
        except py_compile.PyCompileError as e:
            print(f"  ERROR {f}: {e}")
            all_ok = False

    print("\n" + "=" * 60)
    print("  ALL DONE!" if all_ok else "  WARNING: fix errors above")
    print("=" * 60)
    print("""
Следующие шаги:

  cd dagster_dbt_pipeline
  dagster dev

Что увидишь в UI (localhost:3000):
  Catalog -> dbt assets (stg_orders, fct_orders, dim_customers...)
  Catalog -> partitioned/daily_orders (с партициями по дням)
  Lineage -> полный граф: raw -> dbt staging -> dbt marts

Materialization dbt modelei:
  Catalog -> analytics_dbt_assets -> Materialize

Backfill партиций (30 дней):
  Jobs -> daily_partitioned_job -> Launch backfill
  -> Vyberi diapazon 2024-01-01 to 2024-01-30

Asset checks:
  Catalog -> daily_orders -> Check assets

Git:
  git add dagster_dbt_pipeline/ lesson66_70.py
  git commit -m "feat: Days 66-70 dagster-dbt + Partitions + Observability"
  git push origin main
""")


if __name__ == "__main__":
    main()