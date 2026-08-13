#!/usr/bin/env python3
"""
checkpoint_week8.py - Week 8 Checkpoint (Days 46-60)
Запуск: python checkpoint_week8.py
Проверяет: dbt pipeline, Semantic Layer, FastAPI, reports
"""

import subprocess
import duckdb
import requests
import json
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT  = PROJECT_ROOT / "dbt_analytics"
REPORTS_DIR  = PROJECT_ROOT / "reports"
DB_PATH      = DBT_PROJECT / "dev.duckdb"

RESULTS = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    RESULTS[name] = ok
    print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))


def run_dbt(cmd: str) -> tuple[bool, str]:
    r = subprocess.run(
        f"dbt {cmd}", shell=True, cwd=DBT_PROJECT,
        capture_output=True, text=True, encoding="utf-8"
    )
    return r.returncode == 0, r.stdout


# ── БЛОК 1: dbt Pipeline ─────────────────────────────────

def check_dbt_pipeline():
    print("\n" + "=" * 55)
    print("  BLOCK 1: dbt Pipeline")
    print("=" * 55)

    ok, out = run_dbt("run")
    passed = "ERROR=0" in out or "Done. PASS=" in out
    errors = 0
    for line in out.split("\n"):
        if "ERROR=" in line and "ERROR=0" not in line:
            try:
                errors = int(line.split("ERROR=")[1].split()[0])
            except Exception:
                pass
    total = 0
    for line in out.split("\n"):
        if "TOTAL=" in line:
            try:
                total = int(line.split("TOTAL=")[1].split()[0])
            except Exception:
                pass

    check("dbt run: no errors", errors == 0, f"errors={errors}, total={total}")

    ok2, out2 = run_dbt("test")
    t_pass = 0
    t_err  = 0
    for line in out2.split("\n"):
        if "PASS=" in line:
            try:
                t_pass = int(line.split("PASS=")[1].split()[0])
            except Exception:
                pass
        if "ERROR=" in line and "ERROR=0" not in line:
            try:
                t_err = int(line.split("ERROR=")[1].split()[0])
            except Exception:
                pass
    check("dbt test: PASS >= 20", t_pass >= 20, f"PASS={t_pass} ERROR={t_err}")
    check("dbt test: no errors",  t_err == 0,   f"errors={t_err}")

    ok3, out3 = run_dbt("parse")
    check("dbt parse: clean", ok3)


# ── БЛОК 2: Модели в DuckDB ──────────────────────────────

def check_models():
    print("\n" + "=" * 55)
    print("  BLOCK 2: Models in DuckDB")
    print("=" * 55)

    if not DB_PATH.exists():
        check("dev.duckdb exists", False, "Run dbt run first")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()]

    required = ["fct_orders", "dim_customers", "dim_date", "metricflow_time_spine"]
    for t in required:
        check(f"table: {t}", t in tables)

    # Semantic Layer models (Days 51-55)
    metrics_tables = ["metricflow_time_spine"]
    for t in metrics_tables:
        check(f"semantic: {t}", t in tables)

    # Row counts
    for t in ["fct_orders", "dim_customers"]:
        if t in tables:
            cnt = con.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0]
            check(f"{t}: has rows", cnt > 0, f"rows={cnt}")

    con.close()


# ── БЛОК 3: Semantic Layer ───────────────────────────────

def check_semantic_layer():
    print("\n" + "=" * 55)
    print("  BLOCK 3: Semantic Layer (Days 51-55)")
    print("=" * 55)

    metrics_dir = DBT_PROJECT / "models" / "metrics"
    required_files = [
        "_semantic_models.yml",
        "_metrics.yml",
        "_saved_queries.yml",
        "metricflow_time_spine.sql",
        "metricflow_time_spine.yml",
    ]
    for f in required_files:
        check(f"metrics/{f}", (metrics_dir / f).exists())

    # Проверяем что в _metrics.yml есть 8 метрик
    metrics_file = metrics_dir / "_metrics.yml"
    if metrics_file.exists():
        content = metrics_file.read_text(encoding="utf-8")
        metric_count = content.count("  - name:")
        check("_metrics.yml: >= 8 metrics", metric_count >= 8, f"found={metric_count}")


# ── БЛОК 4: Data Contracts ───────────────────────────────

def check_contracts():
    print("\n" + "=" * 55)
    print("  BLOCK 4: Data Contracts (Days 48-50)")
    print("=" * 55)

    contracts_dir = PROJECT_ROOT / "contracts"
    check("contracts/ dir exists", contracts_dir.exists())

    ci_file = DBT_PROJECT / ".github" / "workflows" / "dbt_ci.yml"
    cd_file = DBT_PROJECT / ".github" / "workflows" / "dbt_cd.yml"
    # workflows могут быть в корне проекта
    ci_root = PROJECT_ROOT / ".github" / "workflows" / "dbt_ci.yml"
    cd_root = PROJECT_ROOT / ".github" / "workflows" / "dbt_cd.yml"
    check("CI workflow exists", ci_file.exists() or ci_root.exists())
    check("CD workflow exists", cd_file.exists() or cd_root.exists())


# ── БЛОК 5: Snapshots ────────────────────────────────────

def check_snapshots():
    print("\n" + "=" * 55)
    print("  BLOCK 5: Snapshots (Days 46)")
    print("=" * 55)

    if not DB_PATH.exists():
        check("snapshots in DB", False, "no DB")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)
    snap_tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_name LIKE 'snap_%'"
    ).fetchall()]
    con.close()

    check("snapshots exist", len(snap_tables) > 0, f"found: {snap_tables}")


# ── БЛОК 6: FastAPI ──────────────────────────────────────

def check_fastapi():
    print("\n" + "=" * 55)
    print("  BLOCK 6: FastAPI Metrics API (Days 51-55)")
    print("=" * 55)

    api_file = PROJECT_ROOT / "metrics_api" / "main.py"
    check("metrics_api/main.py exists", api_file.exists())

    # Пробуем достучаться до запущенного сервера
    endpoints = [
        "/",
        "/metrics/catalog",
        "/metrics/summary",
        "/metrics/by-city",
        "/metrics/ltv-report",
    ]
    for ep in endpoints:
        try:
            resp = requests.get(f"http://localhost:8001{ep}", timeout=3)
            check(f"GET {ep}", resp.status_code == 200,
                  f"status={resp.status_code}")
        except Exception:
            check(f"GET {ep}", False, "server not running (start uvicorn)")


# ── БЛОК 7: Reports ──────────────────────────────────────

def check_reports():
    print("\n" + "=" * 55)
    print("  BLOCK 7: Analytics Reports (Days 56-60)")
    print("=" * 55)

    expected = ["rfm_segments.csv", "cohort_retention.csv", "ltv_by_city.csv"]
    for f in expected:
        path = REPORTS_DIR / f
        check(f"reports/{f}", path.exists(),
              f"rows={sum(1 for _ in open(path))}" if path.exists() else "missing")


# ── ИТОГ ─────────────────────────────────────────────────

def print_summary():
    print("\n" + "=" * 55)
    print("  WEEK 8 CHECKPOINT SUMMARY")
    print("=" * 55)

    passed = sum(1 for v in RESULTS.values() if v)
    total  = len(RESULTS)
    pct    = passed * 100 // total if total else 0

    print(f"\n  Result: {passed}/{total} checks passed ({pct}%)\n")

    if pct == 100:
        print("  STATUS: PERFECT - Ready for Month 2 Project!")
    elif pct >= 80:
        print("  STATUS: GOOD - Fix failing checks above")
    else:
        print("  STATUS: NEEDS WORK - Run dbt pipeline first")

    failed = [k for k, v in RESULTS.items() if not v]
    if failed:
        print("\n  Failed checks:")
        for f in failed:
            print(f"    - {f}")

    report_path = REPORTS_DIR / f"checkpoint_week8_{date.today()}.json"
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path.write_text(
        json.dumps({"date": str(date.today()), "passed": passed,
                    "total": total, "results": RESULTS}, indent=2),
        encoding="utf-8"
    )
    print(f"\n  Report: {report_path.name}")


def main():
    print("=" * 55)
    print("  Week 8 Checkpoint (Days 46-60)")
    print("=" * 55)

    check_dbt_pipeline()
    check_models()
    check_semantic_layer()
    check_contracts()
    check_snapshots()
    check_fastapi()
    check_reports()
    print_summary()


if __name__ == "__main__":
    main()