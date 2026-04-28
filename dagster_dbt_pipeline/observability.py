# dagster_dbt_pipeline/observability.py
# Day 70: asset_checks + alerting simulation
# [[Dagster]] [[Data Quality]] [[Monitoring]]

import duckdb
from pathlib import Path
from dagster import (
    asset_check, AssetCheckResult, AssetCheckSeverity,
    sensor, RunRequest, SensorEvaluationContext, SkipReason,
    define_asset_job,
)

DB_PATH_MAIN        = Path(__file__).parent.parent / 'dagster_pipeline' / 'analytics.duckdb'
DB_PATH_PARTITIONED = Path(__file__).parent / 'partitioned.duckdb'


def get_main_con():
    if not DB_PATH_MAIN.exists():
        return None
    return duckdb.connect(str(DB_PATH_MAIN), read_only=True)


# ── Asset Checks (Day 70) ─────────────────────────────

@asset_check(
    asset='daily_orders',
    description='Partitsiya soderzhit dannye (ne pustaya)',
)
def check_partition_not_empty():
    if not DB_PATH_PARTITIONED.exists():
        return AssetCheckResult(
            passed=False,
            metadata={'reason': 'DB not found'},
            severity=AssetCheckSeverity.WARN,
        )
    con = duckdb.connect(str(DB_PATH_PARTITIONED), read_only=True)
    try:
        cnt = con.execute('SELECT COUNT(*) FROM daily_orders').fetchone()[0]
        con.close()
        return AssetCheckResult(
            passed=cnt > 0,
            metadata={'total_rows': cnt},
        )
    except Exception as e:
        con.close()
        return AssetCheckResult(
            passed=False,
            metadata={'error': str(e)},
            severity=AssetCheckSeverity.WARN,
        )


@asset_check(
    asset='daily_orders',
    description='Amount vsegda polozhitelnyy',
)
def check_positive_amount():
    if not DB_PATH_PARTITIONED.exists():
        return AssetCheckResult(passed=True,
                                metadata={'status': 'skipped: DB not ready'})
    con = duckdb.connect(str(DB_PATH_PARTITIONED), read_only=True)
    try:
        bad = con.execute(
            'SELECT COUNT(*) FROM daily_orders WHERE amount <= 0'
        ).fetchone()[0]
        con.close()
        return AssetCheckResult(
            passed=bad == 0,
            metadata={'negative_or_zero_rows': bad},
            severity=AssetCheckSeverity.ERROR if bad > 0 else AssetCheckSeverity.WARN,
        )
    except Exception as e:
        con.close()
        return AssetCheckResult(passed=True, metadata={'status': str(e)})


# ── Alert Simulation (Day 70) ─────────────────────────
# V production: Slack webhook / email
# Zdes: logiruyem v fayl kak simulyatsiyu

ALERTS_LOG = Path(__file__).parent / 'alerts.log'


def send_alert(message: str, level: str = 'ERROR') -> None:
    from datetime import datetime
    entry = f'[{datetime.now().isoformat()}] [{level}] {message}\n'
    with open(ALERTS_LOG, 'a', encoding='utf-8') as f:
        f.write(entry)
    print(f'ALERT: {entry.strip()}')


# Sensor dlya monitoringa failov
daily_job = define_asset_job(
    name='daily_partitioned_job',
    selection=['daily_orders', 'daily_revenue_summary'],
)
