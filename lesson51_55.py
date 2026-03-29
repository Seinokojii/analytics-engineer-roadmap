#!/usr/bin/env python3
"""
lesson51_55.py - dbt Semantic Layer + MetricFlow
Days 51-55

Chto delaet:
  1. Sozdaet dbt_analytics/metrics/ s tremya YAML failami
  2. Obnovlyaet dbt_project.yml (dobavlyaet metric-paths)
  3. Sozdaet metrics_api/ (FastAPI server)
  4. Zapuskaet dbt parse dlya validacii

Zapusk:
    python lesson51_55.py
"""

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT  = PROJECT_ROOT / "dbt_analytics"
METRICS_DIR  = DBT_PROJECT  / "models" / "metrics"   # <-- inside models/
API_DIR      = PROJECT_ROOT / "metrics_api"


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


def run(cmd: str, cwd: Path = DBT_PROJECT) -> bool:
    print(f"\n> {cmd}")
    r = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, encoding="utf-8"
    )
    if r.stdout:
        print(r.stdout)
    if r.returncode != 0:
        print(f"ERROR:\n{r.stderr}")
        return False
    return True


# --- FAIL 1: _semantic_models.yml -------------------------------------------

SEMANTIC_MODELS = """\
# metrics/_semantic_models.yml
# [[Semantic Layer]] -- opisanie tablic dlya [[MetricFlow]]

semantic_models:

  - name: orders
    description: "Zakazy -- osnova dlya revenue/AOV/order_count"
    model: ref('fct_orders')

    entities:
      - name: order
        type: primary
        expr: order_id
      - name: customer
        type: foreign
        expr: user_id

    dimensions:
      - name: order_date
        type: time
        expr: order_date
        type_params:
          time_granularity: day
      - name: city
        type: categorical
        expr: city

    measures:
      - name: revenue
        agg: sum
        expr: amount
        description: "Vyruchka (SUM amount)"
        agg_time_dimension: order_date
        create_metric: false
      - name: order_count
        agg: count_distinct
        expr: order_id
        agg_time_dimension: order_date
        create_metric: false
      - name: spending_customers
        agg: count_distinct
        expr: user_id
        agg_time_dimension: order_date
        create_metric: false

  - name: customers
    description: "Klienty -- osnova dlya customer_count/LTV"
    model: ref('dim_customers')

    entities:
      - name: customer
        type: primary
        expr: user_id

    dimensions:
      - name: registration_date
        type: time
        expr: registration_date
        type_params:
          time_granularity: day
      - name: city
        type: categorical
        expr: city

    measures:
      - name: customer_count
        agg: count_distinct
        expr: user_id
        agg_time_dimension: registration_date
        create_metric: false
      - name: total_customer_spending
        agg: sum
        expr: total_spent
        agg_time_dimension: registration_date
        create_metric: false
"""

# --- FAIL 2: _metrics.yml ----------------------------------------------------

METRICS = """\
# metrics/_metrics.yml
# [[MetricFlow]] -- 8 biznes-metrik

metrics:

  - name: total_revenue
    description: "SUM(amount) -- edinstvennoe opredelenie revenue"
    type: simple
    label: "Total Revenue"
    type_params:
      measure: revenue

  - name: order_count
    description: "COUNT_DISTINCT(order_id)"
    type: simple
    label: "Order Count"
    type_params:
      measure: order_count

  - name: customer_count
    description: "COUNT_DISTINCT(user_id) -- pokupavshie klienty"
    type: simple
    label: "Active Customers"
    type_params:
      measure: spending_customers

  - name: average_order_value
    description: "AOV = total_revenue / order_count"
    type: ratio
    label: "Average Order Value"
    type_params:
      numerator: total_revenue
      denominator: order_count

  - name: revenue_per_customer
    description: "ARPU-proksi = total_revenue / customer_count"
    type: ratio
    label: "Revenue per Customer (ARPU proxy)"
    type_params:
      numerator: total_revenue
      denominator: customer_count

  - name: cumulative_revenue
    description: "Narastayushchaya vyruchka (cumulative SUM)"
    type: cumulative
    label: "Cumulative Revenue"
    type_params:
      measure: revenue

  - name: ltv_simple
    description: "LTV = revenue_per_customer / 0.05 (churn=5%)"
    type: derived
    label: "LTV Simple"
    type_params:
      expr: revenue_per_customer / 0.05
      metrics:
        - name: revenue_per_customer

  - name: total_customer_ltv
    description: "Istoricheskiy LTV: SUM(total_spent) iz dim_customers"
    type: simple
    label: "Historical Customer LTV"
    type_params:
      measure: total_customer_spending
"""

# --- FAIL 3: _saved_queries.yml ----------------------------------------------

SAVED_QUERIES = """\
# metrics/_saved_queries.yml
# Gotovye zaprosy dlya [[Power BI]] i [[FastAPI]]

saved_queries:

  - name: executive_kpi_daily
    description: "Ezhednevnye KPI dlya Executive Dashboard"
    query_params:
      metrics:
        - total_revenue
        - order_count
        - customer_count
        - average_order_value
      group_by:
        - TimeDimension('order__order_date', 'day')
    exports:
      - name: executive_kpi_daily
        config:
          export_as: table
          schema: semantic_exports
          alias: executive_kpi_daily

  - name: revenue_by_city
    description: "Revenue + AOV po gorodam"
    query_params:
      metrics:
        - total_revenue
        - order_count
        - average_order_value
      group_by:
        - Dimension('order__city')

  - name: ltv_report
    description: "LTV: predskazatelnyy vs istoricheskiy"
    query_params:
      metrics:
        - ltv_simple
        - total_customer_ltv
        - revenue_per_customer
      group_by:
        - Dimension('customer__city')
"""


# --- TIME SPINE (required by MetricFlow) ------------------------------------

TIME_SPINE_SQL = """-- models/metrics/metricflow_time_spine.sql
-- Required by MetricFlow: provides date spine for time dimensions.
-- Pure DuckDB generate_series -- no dbt_utils macro needed.

{{ config(materialized='table') }}

SELECT
    CAST(gs AS DATE) AS date_day
FROM GENERATE_SERIES(
    DATE '2020-01-01',
    DATE '2030-01-01',
    INTERVAL '1 day'
) AS t(gs)
"""

TIME_SPINE_YML = """# models/metrics/metricflow_time_spine.yml
models:
  - name: metricflow_time_spine
    description: "Time spine required by [[MetricFlow]] for temporal metrics."
    time_spine:
      standard_granularity_column: date_day
    columns:
      - name: date_day
        granularity: day
"""

# --- FAIL 4: FastAPI main.py -------------------------------------------------
# VAZNO: ispolzuem slozhenie strok (a + b), a ne triple-quotes,
# chtoby vnutrennie """ ne zakryvali vneshniy literal.

_L = "\n"

FASTAPI_MAIN = (
    "# metrics_api/main.py\n"
    "# FastAPI -- Single Source of Truth dlya metrik\n"
    "\n"
    "from fastapi import FastAPI, HTTPException, Query\n"
    "from fastapi.middleware.cors import CORSMiddleware\n"
    "import duckdb\n"
    "from pathlib import Path\n"
    "from typing import Optional\n"
    "\n"
    "app = FastAPI(\n"
    "    title='Analytics Metrics API',\n"
    "    description='Single Source of Truth. Powered by dbt Semantic Layer.',\n"
    "    version='1.0.0',\n"
    ")\n"
    "app.add_middleware(\n"
    "    CORSMiddleware,\n"
    "    allow_origins=['*'],\n"
    "    allow_methods=['*'],\n"
    "    allow_headers=['*'],\n"
    ")\n"
    "\n"
    "DB_PATH = Path(__file__).parent.parent / 'dbt_analytics' / 'dev.duckdb'\n"
    "\n"
    "\n"
    "def get_con():\n"
    "    if not DB_PATH.exists():\n"
    "        raise HTTPException(503, f'Database not found: {DB_PATH}. Run dbt run first.')\n"
    "    return duckdb.connect(str(DB_PATH), read_only=True)\n"
    "\n"
    "\n"
    "@app.get('/', tags=['info'])\n"
    "def root():\n"
    "    return {\n"
    "        'service': 'Analytics Metrics API',\n"
    "        'endpoints': [\n"
    "            '/metrics/catalog',\n"
    "            '/metrics/summary',\n"
    "            '/metrics/by-city',\n"
    "            '/metrics/revenue-trend',\n"
    "            '/metrics/ltv-report',\n"
    "        ],\n"
    "    }\n"
    "\n"
    "\n"
    "@app.get('/metrics/catalog', tags=['catalog'])\n"
    "def catalog():\n"
    "    # Katalog 8 metrik (sootvetstvuet _metrics.yml)\n"
    "    return {\n"
    "        'metrics': {\n"
    "            'total_revenue':        'SUM(amount)',\n"
    "            'order_count':          'COUNT_DISTINCT(order_id)',\n"
    "            'customer_count':       'COUNT_DISTINCT(user_id)',\n"
    "            'average_order_value':  'total_revenue / order_count',\n"
    "            'revenue_per_customer': 'total_revenue / customer_count',\n"
    "            'cumulative_revenue':   'SUM(amount) rolling',\n"
    "            'ltv_simple':           'revenue_per_customer / 0.05',\n"
    "            'total_customer_ltv':   'SUM(total_spent) iz dim_customers',\n"
    "        }\n"
    "    }\n"
    "\n"
    "\n"
    "@app.get('/metrics/summary', tags=['metrics'])\n"
    "def summary(\n"
    "    start_date: Optional[str] = Query(None, description='YYYY-MM-DD'),\n"
    "    end_date:   Optional[str] = Query(None, description='YYYY-MM-DD'),\n"
    "):\n"
    "    con = get_con()\n"
    "    date_filter = ''\n"
    "    if start_date and end_date:\n"
    "        date_filter = f\"AND order_date BETWEEN '{start_date}' AND '{end_date}'\"\n"
    "    elif start_date:\n"
    "        date_filter = f\"AND order_date >= '{start_date}'\"\n"
    "\n"
    "    q = (\n"
    "        'SELECT '\n"
    "        'ROUND(SUM(amount), 2) AS total_revenue, '\n"
    "        'COUNT(DISTINCT order_id) AS order_count, '\n"
    "        'COUNT(DISTINCT user_id) AS customer_count, '\n"
    "        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT order_id),0),2) AS average_order_value, '\n"
    "        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT user_id),0),2) AS revenue_per_customer, '\n"
    "        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT user_id),0)/0.05,2) AS ltv_simple '\n"
    "        'FROM main.fct_orders WHERE 1=1 '\n"
    "    ) + date_filter\n"
    "    try:\n"
    "        r = con.execute(q).fetchone()\n"
    "        con.close()\n"
    "        return {\n"
    "            'period': {'start': start_date, 'end': end_date},\n"
    "            'metrics': {\n"
    "                'total_revenue':        r[0],\n"
    "                'order_count':          r[1],\n"
    "                'customer_count':       r[2],\n"
    "                'average_order_value':  r[3],\n"
    "                'revenue_per_customer': r[4],\n"
    "                'ltv_simple':           r[5],\n"
    "            },\n"
    "        }\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        raise HTTPException(500, str(e))\n"
    "\n"
    "\n"
    "@app.get('/metrics/by-city', tags=['metrics'])\n"
    "def by_city(limit: int = Query(10, ge=1, le=100)):\n"
    "    con = get_con()\n"
    "    q = (\n"
    "        'SELECT city, '\n"
    "        'ROUND(SUM(amount),2) AS total_revenue, '\n"
    "        'COUNT(DISTINCT order_id) AS order_count, '\n"
    "        'COUNT(DISTINCT user_id) AS customer_count, '\n"
    "        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT order_id),0),2) AS average_order_value '\n"
    "        'FROM main.fct_orders WHERE city IS NOT NULL '\n"
    "        'GROUP BY city ORDER BY total_revenue DESC '\n"
    "        f'LIMIT {limit}'\n"
    "    )\n"
    "    try:\n"
    "        rows = con.execute(q).fetchall()\n"
    "        cols = ['city', 'total_revenue', 'order_count',\n"
    "                'customer_count', 'average_order_value']\n"
    "        con.close()\n"
    "        return {'data': [dict(zip(cols, r)) for r in rows]}\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        raise HTTPException(500, str(e))\n"
    "\n"
    "\n"
    "@app.get('/metrics/revenue-trend', tags=['metrics'])\n"
    "def revenue_trend(\n"
    "    granularity: str = Query('month', description='day | week | month'),\n"
    "    periods:     int  = Query(12, ge=1, le=36),\n"
    "):\n"
    "    if granularity not in ('day', 'week', 'month'):\n"
    "        raise HTTPException(400, 'granularity: day | week | month')\n"
    "    con = get_con()\n"
    "    q = (\n"
    "        f\"SELECT DATE_TRUNC('{granularity}', order_date) AS period, \"\n"
    "        'ROUND(SUM(amount),2) AS revenue, '\n"
    "        'COUNT(DISTINCT order_id) AS orders, '\n"
    "        f\"ROUND(SUM(SUM(amount)) OVER (ORDER BY DATE_TRUNC('{granularity}', order_date)),2) \"\n"
    "        'AS cumulative_revenue '\n"
    "        'FROM main.fct_orders '\n"
    "        f\"WHERE order_date >= (SELECT MAX(order_date) - INTERVAL '{periods} {granularity}s' \"\n"
    "        'FROM main.fct_orders) '\n"
    "        f\"GROUP BY DATE_TRUNC('{granularity}', order_date) ORDER BY period\"\n"
    "    )\n"
    "    try:\n"
    "        rows = con.execute(q).fetchall()\n"
    "        cols = ['period', 'revenue', 'orders', 'cumulative_revenue']\n"
    "        con.close()\n"
    "        return {\n"
    "            'granularity': granularity,\n"
    "            'data': [{**dict(zip(cols, r)), 'period': str(r[0])} for r in rows],\n"
    "        }\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        raise HTTPException(500, str(e))\n"
    "\n"
    "\n"
    "@app.get('/metrics/ltv-report', tags=['metrics'])\n"
    "def ltv_report():\n"
    "    con = get_con()\n"
    "    q = (\n"
    "        'SELECT city, '\n"
    "        'COUNT(DISTINCT user_id) AS customers, '\n"
    "        'ROUND(AVG(total_spent),2) AS avg_historical_ltv, '\n"
    "        'ROUND(AVG(avg_order_value),2) AS avg_order_value, '\n"
    "        'ROUND(AVG(total_spent/0.05),2) AS avg_predictive_ltv '\n"
    "        'FROM main.dim_customers '\n"
    "        'WHERE total_spent > 0 '\n"
    "        'GROUP BY city ORDER BY avg_historical_ltv DESC LIMIT 10'\n"
    "    )\n"
    "    try:\n"
    "        rows = con.execute(q).fetchall()\n"
    "        cols = ['city', 'customers', 'avg_historical_ltv',\n"
    "                'avg_order_value', 'avg_predictive_ltv']\n"
    "        con.close()\n"
    "        return {'data': [dict(zip(cols, r)) for r in rows]}\n"
    "    except Exception as e:\n"
    "        con.close()\n"
    "        raise HTTPException(500, str(e))\n"
)

FASTAPI_REQUIREMENTS = """\
fastapi==0.115.0
uvicorn==0.30.0
duckdb==1.1.3
"""


# --- Obnovlenie dbt_project.yml ----------------------------------------------

def update_dbt_project() -> None:
    # metric-paths is NOT valid in dbt_project.yml (dbt 1.x).
    # Semantic Layer YAMLs live inside models/ -- no config needed.
    # This function cleans up the key if added by a previous run.
    path = DBT_PROJECT / "dbt_project.yml"
    if not path.exists():
        print("  WARNING: dbt_project.yml not found -- skip")
        return
    content = path.read_text(encoding="utf-8")
    if 'metric-paths: ["metrics"]' in content:
        content = content.replace('metric-paths: ["metrics"]\n\n', "")
        path.write_text(content, encoding="utf-8")
        print("  OK dbt_project.yml cleaned: removed invalid metric-paths key")
    else:
        print("  OK dbt_project.yml: no changes needed")


# --- MAIN --------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  Days 51-55: dbt Semantic Layer + MetricFlow")
    print("=" * 60)

    print("\n[1/4] Semantic Layer YAML files + time spine...")
    write_utf8(METRICS_DIR / "_semantic_models.yml",      SEMANTIC_MODELS)
    write_utf8(METRICS_DIR / "_metrics.yml",              METRICS)
    write_utf8(METRICS_DIR / "_saved_queries.yml",        SAVED_QUERIES)
    write_utf8(METRICS_DIR / "metricflow_time_spine.sql", TIME_SPINE_SQL)
    write_utf8(METRICS_DIR / "metricflow_time_spine.yml", TIME_SPINE_YML)

    print("\n[2/4] Update dbt_project.yml...")
    update_dbt_project()

    print("\n[3/4] FastAPI Metrics API...")
    write_utf8(API_DIR / "main.py",          FASTAPI_MAIN)
    write_utf8(API_DIR / "requirements.txt", FASTAPI_REQUIREMENTS)

    print("\n[4/4] dbt parse (validation)...")
    ok = run("dbt parse")

    print("\n" + "=" * 60)
    print("ALL DONE!" if ok else "WARNING: dbt parse failed -- check paths above")
    print("=" * 60)
    print("""
Next steps:
  cd dbt_analytics && dbt run && dbt test
  cd ../metrics_api && pip install -r requirements.txt
  uvicorn main:app --reload --port 8001

API:
  http://localhost:8001/docs
  http://localhost:8001/metrics/summary
  http://localhost:8001/metrics/by-city
  http://localhost:8001/metrics/revenue-trend
  http://localhost:8001/metrics/ltv-report

Git:
  git add dbt_analytics/metrics/ metrics_api/ lesson51_55.py
  git commit -m "feat: dbt Semantic Layer + MetricFlow (Days 51-55)"
  git push origin main
""")


if __name__ == "__main__":
    main()