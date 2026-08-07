"""
production_pipeline/assets_ingest.py
Day 81-85: Airbyte sync kak Dagster asset s dnevnymi partitsiyami.

V production zdes stoit trigger realnogo Airbyte sync (sm. airbyte_trigger.py).
Lokalno - ta zhe funktsiya sync_partition, chtoby graf i partitsii byli nastoyashchie.
"""

from pathlib import Path

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    DailyPartitionsDefinition,
    Backoff,
    Jitter,
    Output,
    RetryPolicy,
    asset,
)

from ingest_core import RAW_TABLE, sync_partition

PIPELINE_DIR = Path(__file__).parent
DBT_DB = PIPELINE_DIR.parent / "dbt_analytics" / "analytics.duckdb"
SOURCE_CSV = PIPELINE_DIR / "source_data" / "gh_events.csv"

# 1 partitsiya = 1 sutki. Inkrementalnyy zapusk kazhdye 24 chasa.
daily_partitions = DailyPartitionsDefinition(
    start_date="2026-07-08",
    timezone="UTC",
)


@asset(
    key=["raw", RAW_TABLE],
    partitions_def=daily_partitions,
    group_name="ingest",
    kinds={"airbyte", "duckdb"},
    description="Airbyte sync GitHub Events -> raw schema (1 partitsiya = 1 den)",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=1),
    # Vtoroy uroven zashchity ot gonki za DuckDB (pervyy - ochered v dagster.yaml).
    # Setevoy ingest voobshche padaet regulyarno: timeout, 503, rate limit.
    # Retry s exponential backoff - standart dlya lyubogo ingest asseta.
    retry_policy=RetryPolicy(
        max_retries=3,
        delay=2,
        backoff=Backoff.EXPONENTIAL,
        jitter=Jitter.PLUS_MINUS,
    ),
)
def airbyte_raw_gh_events(context: AssetExecutionContext) -> Output:
    partition_date = context.partition_key
    context.log.info(f"Airbyte sync for partition {partition_date}")

    result = sync_partition(DBT_DB, SOURCE_CSV, partition_date)

    if result["rows_synced"] == 0:
        context.log.warning(f"Empty sync for {partition_date}")

    return Output(
        value=result["rows_synced"],
        metadata={
            "partition_date": result["partition_date"],
            "rows_synced": result["rows_synced"],
            "rows_total_in_raw": result["rows_total"],
            "extracted_at": result["extracted_at"],
        },
    )
