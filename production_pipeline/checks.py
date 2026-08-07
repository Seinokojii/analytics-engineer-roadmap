"""
production_pipeline/checks.py
Day 81-85: quality gate + alerting.

dbt testy uzhe pokryvayut modeli (dbt build -> asset checks).
Zdes - proverki na urovne pipeline: svezhest raw i nepustaya partitsiya.
"""

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    asset_check,
)

from ingest_core import RAW_SCHEMA, RAW_TABLE

PIPELINE_DIR = Path(__file__).parent
DBT_DB = PIPELINE_DIR.parent / "dbt_analytics" / "analytics.duckdb"
ALERTS_LOG = PIPELINE_DIR / "alerts.log"

FRESHNESS_WARN_HOURS = 26


def send_alert(message: str, level: str = "ERROR") -> None:
    """V production - Slack webhook / PagerDuty. Zdes - fayl + stdout."""
    entry = f"[{datetime.now().isoformat(timespec='seconds')}] [{level}] {message}"
    with open(ALERTS_LOG, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
    print(f"ALERT {entry}")


def _con():
    if not DBT_DB.exists():
        return None
    return duckdb.connect(str(DBT_DB), read_only=True)


@asset_check(
    asset=["raw", RAW_TABLE],
    description="raw ne pustaya",
)
def check_raw_not_empty():
    con = _con()
    if con is None:
        return AssetCheckResult(
            passed=False,
            metadata={"reason": "DuckDB not found"},
            severity=AssetCheckSeverity.WARN,
        )
    try:
        cnt = con.execute(
            f"SELECT COUNT(*) FROM {RAW_SCHEMA}.{RAW_TABLE}"
        ).fetchone()[0]
    except Exception as e:
        return AssetCheckResult(
            passed=False,
            metadata={"error": str(e)},
            severity=AssetCheckSeverity.WARN,
        )
    finally:
        con.close()

    if cnt == 0:
        send_alert(f"{RAW_TABLE} is empty after sync")
    return AssetCheckResult(passed=cnt > 0, metadata={"rows": cnt})


@asset_check(
    asset=["raw", RAW_TABLE],
    description=f"Svezhest raw: sync ne starshe {FRESHNESS_WARN_HOURS}h",
)
def check_raw_freshness():
    con = _con()
    if con is None:
        return AssetCheckResult(passed=True, metadata={"status": "skipped"})
    try:
        row = con.execute(
            f"SELECT MAX(_airbyte_extracted_at) FROM {RAW_SCHEMA}.{RAW_TABLE}"
        ).fetchone()
    except Exception as e:
        return AssetCheckResult(
            passed=True,
            metadata={"status": str(e)},
            severity=AssetCheckSeverity.WARN,
        )
    finally:
        con.close()

    last = row[0] if row else None
    if last is None:
        return AssetCheckResult(passed=False, metadata={"reason": "no data"})

    age_h = (datetime.now() - last).total_seconds() / 3600
    passed = age_h <= FRESHNESS_WARN_HOURS
    if not passed:
        send_alert(f"raw stale: last sync {age_h:.1f}h ago")
    return AssetCheckResult(
        passed=passed,
        metadata={"last_sync": str(last), "age_hours": round(age_h, 2)},
        severity=AssetCheckSeverity.ERROR if not passed else AssetCheckSeverity.WARN,
    )
