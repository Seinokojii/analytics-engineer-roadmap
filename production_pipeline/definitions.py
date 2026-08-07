"""
production_pipeline/definitions.py
Day 81-85: tochka vkhoda. Zapusk: dagster dev -f definitions.py

Skvoznoy graf:
  raw/airbyte_raw_gh_events (Airbyte sync, dnevnye partitsii)
      -> stg_gh_events (dbt view)
          -> mart_daily_events (dbt incremental)
          -> mart_repo_activity (dbt table)
Plus asset checks (svezhest + nepustaya raw) i dbt testy iz dbt build.
Schedule: kazhdyy den v 05:00 UTC.
"""

from dagster import (
    AssetSelection,
    Definitions,
    ScheduleDefinition,
    define_asset_job,
)
from dagster_dbt import DbtCliResource

from assets_dbt import DBT_EXECUTABLE, analytics_dbt_assets, dbt_project
from assets_ingest import airbyte_raw_gh_events
from checks import check_raw_freshness, check_raw_not_empty

# Ne AssetSelection.all(): v dbt_analytics 40 modeley, nakoplennykh s Day 17,
# chast iz nikh Snowflake-only i v DuckDB ne soberetsya.
# Berem tolko ingest asset i vse, chto nizhe po grafu.
production_job = define_asset_job(
    name="production_pipeline_job",
    selection=AssetSelection.assets(["raw", "airbyte_raw_gh_events"]).downstream(),
    description="Airbyte sync -> dbt build -> quality checks",
)

daily_schedule = ScheduleDefinition(
    name="production_pipeline_daily",
    job=production_job,
    cron_schedule="0 5 * * *",
    description="Inkrementalnyy zapusk kazhdye 24 chasa",
)

defs = Definitions(
    assets=[airbyte_raw_gh_events, analytics_dbt_assets],
    asset_checks=[check_raw_not_empty, check_raw_freshness],
    jobs=[production_job],
    schedules=[daily_schedule],
    resources={
        # dbt_executable yavno: inache voz'metsya dbt iz PATH (mozhet byt Fusion)
        "dbt": DbtCliResource(
            project_dir=dbt_project,
            dbt_executable=str(DBT_EXECUTABLE),
        )
    },
)
