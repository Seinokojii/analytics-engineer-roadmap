# dagster_pipeline/asset_checks.py
# Quality checks dlya assets -- analog dbt test
# [[Dagster]] [[Data Quality]]

import duckdb
from pathlib import Path
from dagster import asset_check, AssetCheckResult, AssetCheckSeverity

DB_PATH = Path(__file__).parent / 'analytics.duckdb'


def get_con():
    return duckdb.connect(str(DB_PATH), read_only=True)


@asset_check(asset='fct_orders', description='Net zakazov s otricatelnym sumoy')
def check_no_negative_amount():
    con = get_con()
    bad = con.execute('SELECT COUNT(*) FROM fct_orders WHERE amount < 0').fetchone()[0]
    con.close()
    return AssetCheckResult(
        passed=bad == 0,
        metadata={'negative_rows': bad},
        severity=AssetCheckSeverity.ERROR,
    )


@asset_check(asset='fct_orders', description='Vse order_id unikalnye')
def check_unique_order_ids():
    con = get_con()
    total = con.execute('SELECT COUNT(*) FROM fct_orders').fetchone()[0]
    uniq  = con.execute('SELECT COUNT(DISTINCT order_id) FROM fct_orders').fetchone()[0]
    con.close()
    return AssetCheckResult(
        passed=total == uniq,
        metadata={'total': total, 'unique': uniq, 'duplicates': total - uniq},
    )


@asset_check(asset='stg_orders', description='Net NULL v amount')
def check_no_null_amount():
    con = get_con()
    nulls = con.execute('SELECT COUNT(*) FROM stg_orders WHERE amount IS NULL').fetchone()[0]
    con.close()
    return AssetCheckResult(passed=nulls == 0, metadata={'null_rows': nulls})
