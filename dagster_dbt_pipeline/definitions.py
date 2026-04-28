# dagster_dbt_pipeline/definitions.py
# Entry point dlya dagster dev
# [[Dagster]] [[dbt]] + Partitions + Observability

from dagster import Definitions, ScheduleDefinition
from dagster_dbt import DbtCliResource

from dbt_assets import analytics_dbt_assets, dbt_project
from partitioned_assets import daily_orders, daily_revenue_summary
from observability import (
    check_partition_not_empty, check_positive_amount,
    daily_job,
)

# Resource: kak zapuskat dbt CLI
dbt_resource = DbtCliResource(project_dir=dbt_project)

# Schedule: kazhdoe utro v 6:00
dbt_schedule = ScheduleDefinition(
    name='daily_dbt_schedule',
    job_name='__ASSET_JOB',
    cron_schedule='0 6 * * *',
    description='Ezhednevnyy dbt run v 6:00 UTC',
)

defs = Definitions(
    assets=[
        analytics_dbt_assets,   # vse dbt modeli
        daily_orders,           # partitioned asset
        daily_revenue_summary,  # downstream ot daily_orders
    ],
    asset_checks=[
        check_partition_not_empty,
        check_positive_amount,
    ],
    jobs=[
        daily_job,
    ],
    resources={
        'dbt': dbt_resource,
    },
)
