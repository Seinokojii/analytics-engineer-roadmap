# dagster_pipeline/schedules_sensors.py
# Day 65: @schedule + @sensor + RunConfig
# [[Dagster]] [[Scheduling]]

from dagster import (
    define_asset_job, ScheduleDefinition,
    sensor, RunRequest, SensorEvaluationContext,
    SkipReason,
)
from pathlib import Path
import json

DATA_DIR = Path(__file__).parent / 'data'
INBOX    = Path(__file__).parent / 'inbox'
INBOX.mkdir(exist_ok=True)

# ── Jobs ─────────────────────────────────────────────

# Zapuskaet ves pipeline: raw -> stg -> fct -> dims
full_pipeline_job = define_asset_job(
    name='full_pipeline_job',
    selection=[
        'raw_orders', 'raw_users',
        'stg_orders', 'stg_users',
        'fct_orders',
        'dim_customers', 'dim_dates',
    ],
)

# Tolko ingestion
ingestion_job = define_asset_job(
    name='ingestion_job',
    selection=['raw_orders', 'raw_users'],
)

# ── Schedules ────────────────────────────────────────

# Kazhdoe utro v 6:00 UTC
daily_analytics_schedule = ScheduleDefinition(
    name='daily_analytics_schedule',
    job=full_pipeline_job,
    cron_schedule='0 6 * * *',
    description='Ezhednevnyy ETL pipeline v 6:00 UTC',
)

# Kazhdyy ponedelnik
weekly_refresh_schedule = ScheduleDefinition(
    name='weekly_refresh_schedule',
    job=full_pipeline_job,
    cron_schedule='0 4 * * 1',
    description='Ezhenedelnyy polnyy refresh po ponedelnikam v 4:00 UTC',
)

# ── Sensor ───────────────────────────────────────────

@sensor(
    job=ingestion_job,
    description='Zapuskaet ingestion kogda v inbox/ poyavlyaetsya novyy CSV',
    minimum_interval_seconds=30,
)
def new_csv_sensor(context: SensorEvaluationContext):
    # Chitaem kursor (poslednyy obrabotannyy fayl)
    cursor = context.cursor or ''

    new_files = sorted(
        f for f in INBOX.glob('*.csv')
        if f.name > cursor
    )

    if not new_files:
        yield SkipReason(f'No new CSV files in {INBOX}')
        return

    for csv_file in new_files:
        context.log.info(f'New file detected: {csv_file.name}')
        yield RunRequest(
            run_key=csv_file.name,
            run_config={
                'ops': {
                    'raw_orders': {'config': {'source_file': str(csv_file)}}
                }
            },
            tags={'source_file': csv_file.name},
        )

    # Obnovlyaem cursor
    context.update_cursor(new_files[-1].name)
