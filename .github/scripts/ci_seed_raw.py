#!/usr/bin/env python3
"""
.github/scripts/ci_seed_raw.py
Day 86-88: napolnyaet raw tablitsu v CI.

*.duckdb v .gitignore, poetomu v CI BD pustaya. Ispolzuem tot zhe
ingest_core.sync_partition, chto i Dagster asset - odna logika
ingestion na lokal, prod i CI.
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "production_pipeline"))

from ingest_core import sync_partition  # noqa: E402

CSV = ROOT / "production_pipeline" / "source_data" / "gh_events.csv"
DB = ROOT / "dbt_analytics" / "ci_analytics.duckdb"


def main() -> None:
    dates = sorted(pd.read_csv(CSV)["event_date"].unique())
    print(f"partitions: {dates}")
    for d in dates:
        info = sync_partition(DB, CSV, str(d))
        print(f"  {d}: +{info['rows_synced']} rows (total {info['rows_total']})")
    print("OK: raw seeded")


if __name__ == "__main__":
    main()
