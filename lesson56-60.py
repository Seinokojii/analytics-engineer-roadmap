#!/usr/bin/env python3
"""
lesson56_60.py - Days 56-60: dbt Fusion sim + RFM + Cohort + LTV
Zapusk: python lesson56_60.py
"""

import subprocess
import duckdb
import polars as pl
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT  = PROJECT_ROOT / "dbt_analytics"
REPORTS_DIR  = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def find_db() -> Path:
    """Ishchem .duckdb fail v raznych mestach."""
    candidates = [
        DBT_PROJECT / "dev.duckdb",
        DBT_PROJECT / "dbt_analytics.duckdb",
        PROJECT_ROOT / "dev.duckdb",
    ]
    for p in candidates:
        if p.exists():
            print(f"  DB found: {p.relative_to(PROJECT_ROOT)}")
            return p
    # Fuzzy search
    found = list(DBT_PROJECT.glob("*.duckdb")) + list(PROJECT_ROOT.glob("*.duckdb"))
    if found:
        print(f"  DB found: {found[0].relative_to(PROJECT_ROOT)}")
        return found[0]
    raise FileNotFoundError(
        "dev.duckdb not found. Run: cd dbt_analytics && dbt run"
    )


def run_dbt(cmd: str) -> None:
    print(f"\n[FABRIC NOTEBOOK] % dbt {cmd}")
    r = subprocess.run(
        f"dbt {cmd}", shell=True, cwd=DBT_PROJECT,
        capture_output=True, text=True, encoding="utf-8"
    )
    for line in r.stdout.strip().split("\n")[-5:]:
        print(line)
    if r.returncode != 0:
        print(f"WARNING: {r.stderr[-200:]}")


def get_con():
    db = find_db()
    return duckdb.connect(str(db), read_only=True)


def step1_fabric_pipeline():
    print("\n" + "=" * 55)
    print("  STEP 1: Fabric Notebook Pipeline Simulation")
    print("=" * 55)
    run_dbt("run --select staging")
    run_dbt("run --select marts")
    run_dbt("test")
    print("  OK Pipeline complete")


def step2_rfm():
    print("\n" + "=" * 55)
    print("  STEP 2: RFM Customer Segmentation")
    print("=" * 55)
    con = get_con()
    sql = (
        "WITH metrics AS ("
        " SELECT user_id,"
        "  COUNT(DISTINCT order_id) AS frequency,"
        "  SUM(amount) AS monetary,"
        "  DATEDIFF('day', MAX(order_date), DATE '2025-01-01') AS recency_days"
        " FROM main.fct_orders GROUP BY user_id"
        "),"
        "scored AS ("
        " SELECT *,"
        "  NTILE(4) OVER (ORDER BY recency_days ASC) AS r,"
        "  NTILE(4) OVER (ORDER BY frequency DESC)   AS f,"
        "  NTILE(4) OVER (ORDER BY monetary DESC)    AS m"
        " FROM metrics"
        ")"
        " SELECT *, r+f+m AS rfm_score,"
        "  CASE"
        "   WHEN r+f+m >= 10 THEN 'Champions'"
        "   WHEN r+f+m >= 7  THEN 'Loyal'"
        "   WHEN r >= 3 AND m <= 2 THEN 'New Customers'"
        "   WHEN r <= 2 AND m >= 3 THEN 'At Risk'"
        "   ELSE 'Others'"
        "  END AS segment"
        " FROM scored ORDER BY rfm_score DESC"
    )
    df = con.execute(sql).pl()
    con.close()

    summary = (
        df.group_by("segment")
        .agg(
            pl.len().alias("count"),
            pl.col("monetary").mean().round(2).alias("avg_monetary"),
        )
        .sort("count", descending=True)
    )
    print(summary)
    df.write_csv(REPORTS_DIR / "rfm_segments.csv")
    print(f"  OK rfm_segments.csv ({len(df)} customers)")
    return df


def step3_cohort():
    print("\n" + "=" * 55)
    print("  STEP 3: Cohort Retention Analysis")
    print("=" * 55)
    con = get_con()
    sql = (
        "WITH first_orders AS ("
        " SELECT user_id, DATE_TRUNC('month', MIN(order_date)) AS cohort_month"
        " FROM main.fct_orders GROUP BY user_id"
        "),"
        "activity AS ("
        " SELECT o.user_id, f.cohort_month,"
        "  DATEDIFF('month', f.cohort_month,"
        "   DATE_TRUNC('month', o.order_date)) AS month_num"
        " FROM main.fct_orders o"
        " JOIN first_orders f ON o.user_id = f.user_id"
        "),"
        "agg AS ("
        " SELECT cohort_month, month_num, COUNT(DISTINCT user_id) AS users"
        " FROM activity GROUP BY cohort_month, month_num"
        ")"
        " SELECT cohort_month, month_num, users,"
        "  FIRST_VALUE(users) OVER ("
        "   PARTITION BY cohort_month ORDER BY month_num) AS cohort_size,"
        "  ROUND(users * 100.0 /"
        "   FIRST_VALUE(users) OVER ("
        "   PARTITION BY cohort_month ORDER BY month_num), 1) AS retention_pct"
        " FROM agg WHERE month_num <= 6"
        " ORDER BY cohort_month, month_num"
    )
    df = con.execute(sql).pl()
    con.close()
    print(df.head(12))
    df.write_csv(REPORTS_DIR / "cohort_retention.csv")
    print("  OK cohort_retention.csv")
    return df


def step4_ltv():
    print("\n" + "=" * 55)
    print("  STEP 4: LTV Basic Calculation")
    print("=" * 55)
    con = get_con()
    sql = (
        "WITH customer_ltv AS ("
        " SELECT user_id, city,"
        "  SUM(amount) AS total_spent,"
        "  COUNT(DISTINCT order_id) AS total_orders,"
        "  AVG(amount) AS avg_order_value"
        " FROM main.fct_orders"
        " GROUP BY user_id, city"
        ")"
        " SELECT city,"
        "  COUNT(DISTINCT user_id) AS customers,"
        "  ROUND(AVG(total_spent), 2) AS avg_historical_ltv,"
        "  ROUND(AVG(avg_order_value), 2) AS avg_order_value,"
        "  ROUND(AVG(total_orders), 2) AS avg_orders,"
        "  ROUND(AVG(total_spent) / 0.05, 2) AS predictive_ltv"
        " FROM customer_ltv"
        " WHERE total_spent > 0"
        " GROUP BY city ORDER BY avg_historical_ltv DESC LIMIT 10"
    )
    df = con.execute(sql).pl()
    con.close()
    print(df)
    df.write_csv(REPORTS_DIR / "ltv_by_city.csv")
    print("  OK ltv_by_city.csv")
    return df


def step5_report(rfm_df, cohort_df, ltv_df):
    champions = len(rfm_df.filter(pl.col("segment") == "Champions"))
    at_risk   = len(rfm_df.filter(pl.col("segment") == "At Risk"))
    avg_ret   = cohort_df.filter(pl.col("month_num") == 3)["retention_pct"].mean() or 0
    top_ltv   = ltv_df["avg_historical_ltv"][0]

    report = (
        f"\nDays 56-60 Report\n"
        f"==================\n"
        f"RFM: Champions={champions}, At Risk={at_risk}\n"
        f"Cohort retention month 3: {avg_ret:.1f}%\n"
        f"LTV top city: ${top_ltv:.2f} historical"
        f" / ${top_ltv / 0.05:.2f} predictive\n"
        f"Generated: {date.today()}\n"
    )
    print(report)
    (REPORTS_DIR / f"report_days56_60_{date.today()}.txt").write_text(
        report, encoding="utf-8"
    )
    print("  OK report saved")


def main():
    print("=" * 55)
    print("  Days 56-60: dbt Fusion + RFM + Cohort + LTV")
    print("=" * 55)

    step1_fabric_pipeline()
    rfm_df    = step2_rfm()
    cohort_df = step3_cohort()
    ltv_df    = step4_ltv()
    step5_report(rfm_df, cohort_df, ltv_df)

    print("\nALL DONE!")
    print(
        "\nGit:\n"
        "  git add lesson56_60.py reports/\n"
        '  git commit -m "feat: Days 56-60 dbt Fusion sim + RFM + Cohort + LTV"\n'
        "  git push origin main\n"
    )


if __name__ == "__main__":
    main()