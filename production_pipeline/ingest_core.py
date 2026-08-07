"""
production_pipeline/ingest_core.py
Chistaya funktsiya sync odnoy partitsii. Vyzyvaetsya i iz Dagster asseta,
i iz lesson81_85.py - logika ingestion zhivet v odnom meste.

Emuliruet to, chto delaet Airbyte destination-konnektor:
  source (CSV / API) -> tablitsa raw._airbyte_raw_* s meta-kolonkami
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

RAW_SCHEMA = "raw"
RAW_TABLE = "airbyte_raw_gh_events"


def sync_partition(db_path: Path, csv_path: Path, partition_date: str) -> dict:
    """Zagruzhaet sobytiya za odnu datu v raw tablitsu. Idempotentno.

    DuckDB ne umeet MERGE bez PK -> DELETE + INSERT po partitsii.
    Povtornyy zapusk toy zhe partitsii ne dubliruet stroki.
    """
    df = pd.read_csv(csv_path)
    df = df[df["event_date"] == partition_date].copy()

    extracted_at = datetime.now()
    records = []
    for row in df.to_dict(orient="records"):
        payload = {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "actor": row["actor"],
            "repo": row["repo"],
            "created_at": row["created_at"],
            "payload_size": int(row["payload_size"]),
        }
        records.append(
            {
                "_airbyte_raw_id": str(uuid.uuid4()),
                "_airbyte_data": json.dumps(payload),
                "_airbyte_extracted_at": extracted_at,
                "_airbyte_partition_date": partition_date,
            }
        )

    raw_df = pd.DataFrame(records)

    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {RAW_SCHEMA}.{RAW_TABLE} (
                _airbyte_raw_id         VARCHAR,
                _airbyte_data           VARCHAR,
                _airbyte_extracted_at   TIMESTAMP,
                _airbyte_partition_date DATE
            )
            """
        )
        con.execute(
            f"DELETE FROM {RAW_SCHEMA}.{RAW_TABLE} "
            f"WHERE _airbyte_partition_date = ?",
            [partition_date],
        )
        if records:
            # executemany, a ne con.register(df): pandas 3.0 otdaet novyy
            # string dtype, kotoryy DuckDB 1.1 ne raspoznaet pri registratsii
            con.executemany(
                f"INSERT INTO {RAW_SCHEMA}.{RAW_TABLE} VALUES (?, ?, ?, CAST(? AS DATE))",
                [
                    (
                        r["_airbyte_raw_id"],
                        r["_airbyte_data"],
                        r["_airbyte_extracted_at"],
                        r["_airbyte_partition_date"],
                    )
                    for r in records
                ],
            )
        total = con.execute(
            f"SELECT COUNT(*) FROM {RAW_SCHEMA}.{RAW_TABLE}"
        ).fetchone()[0]
    finally:
        con.close()

    return {
        "partition_date": partition_date,
        "rows_synced": len(raw_df),
        "rows_total": total,
        "extracted_at": extracted_at.isoformat(timespec="seconds"),
    }
