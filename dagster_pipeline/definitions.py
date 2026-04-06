# dagster_pipeline/definitions.py
# Glavnyy entry point dlya Dagster
# 'dagster dev' chitaet etot fayl

from dagster import Definitions
from assets import (
    raw_orders, raw_users,
    stg_orders, stg_users,
    fct_orders, build_dimensions,
)
from schedules_sensors import (
    full_pipeline_job, ingestion_job,
    daily_analytics_schedule, weekly_refresh_schedule,
    new_csv_sensor,
)
from asset_checks import (
    check_no_negative_amount,
    check_unique_order_ids,
    check_no_null_amount,
)

defs = Definitions(
    assets=[
        raw_orders, raw_users,
        stg_orders, stg_users,
        fct_orders, build_dimensions,
    ],
    jobs=[
        full_pipeline_job,
        ingestion_job,
    ],
    schedules=[
        daily_analytics_schedule,
        weekly_refresh_schedule,
    ],
    sensors=[
        new_csv_sensor,
    ],
    asset_checks=[
        check_no_negative_amount,
        check_unique_order_ids,
        check_no_null_amount,
    ],
)
