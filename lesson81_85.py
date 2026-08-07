#!/usr/bin/env python3
"""
lesson81_85.py - Days 81-85: Production Pipeline
Zapusk: python lesson81_85.py

End-to-end pipeline: Airbyte (ingest) -> raw schema -> dbt (transform) -> marts,
orkestratsiya cherez Dagster s dnevnymi partitsiyami.

Chto delaet:
  1. Sozdaet paket production_pipeline/ - Dagster kod vsego pipeline
  2. Generiruet datasset GitHub Events (format GH Archive)
  3. Simuliruet Airbyte sync po dnevnym partitsiyam -> schema raw v DuckDB
  4. Zapuskaet dbt run + dbt test na novykh modelyakh (staging + marts)
  5. Progonyaet quality gate, pri faile pishet alert v alerts.log
  6. Sokhranyaet otchety v reports/

Trebovaniya: .venv s dagster, dagster-dbt, dbt-duckdb, duckdb, pandas
"""

import csv
import importlib.util
import json
import random
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

random.seed(42)

PROJECT_ROOT = Path(__file__).parent
PIPELINE_DIR = PROJECT_ROOT / "production_pipeline"
SOURCE_DIR = PIPELINE_DIR / "source_data"
DBT_PROJECT = PROJECT_ROOT / "dbt_analytics"
DBT_DB = DBT_PROJECT / "analytics.duckdb"
REPORTS_DIR = PROJECT_ROOT / "reports"

for d in (PIPELINE_DIR, SOURCE_DIR, REPORTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Partitsii: poslednie 3 dnya. 1 partitsiya = 1 sutki dannykh.
TODAY = date.today()
PARTITIONS = [(TODAY - timedelta(days=i)).isoformat() for i in (3, 2, 1)]
PARTITION_START = (TODAY - timedelta(days=30)).isoformat()

EVENT_TYPES = ["PushEvent", "PullRequestEvent", "IssuesEvent", "WatchEvent", "ForkEvent"]
REPOS = [
    "dbt-labs/dbt-core",
    "dagster-io/dagster",
    "airbytehq/airbyte",
    "duckdb/duckdb",
    "snowflakedb/snowflake-connector-python",
]
ACTORS = ["diyar", "octocat", "jane-ae", "data-eng-42", "sre-bot", "analyst-99"]


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK {path.relative_to(PROJECT_ROOT)}")


def banner(step: str, title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {step}: {title}")
    print("=" * 60)


# ==========================================================================
# 1. Kod paketa production_pipeline/
# ==========================================================================

INGEST_CORE_PY = '''"""
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
'''

ASSETS_INGEST_PY = '''"""
production_pipeline/assets_ingest.py
Day 81-85: Airbyte sync kak Dagster asset s dnevnymi partitsiyami.

V production zdes stoit trigger realnogo Airbyte sync (sm. airbyte_trigger.py).
Lokalno - ta zhe funktsiya sync_partition, chtoby graf i partitsii byli nastoyashchie.
"""

from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Backoff,
    BackfillPolicy,
    DailyPartitionsDefinition,
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
    start_date="__PARTITION_START__",
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
'''

ASSETS_DBT_PY = '''"""
production_pipeline/assets_dbt.py
Day 81-85: dbt modeli kak Dagster assets, podklyuchennye k ingest assetu.

Klyuchevoy moment: DagsterDbtTranslator mapit dbt source gh_raw.airbyte_raw_gh_events
v AssetKey ["raw", "airbyte_raw_gh_events"] - tot zhe klyuch, chto u ingest asseta.
Poetomu Dagster stroit odin skvoznoy graf: Airbyte -> staging -> marts.
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey
from dagster_dbt import (
    DagsterDbtTranslator,
    DbtCliResource,
    DbtProject,
    dbt_assets,
)

# V PATH mozhet stoyat dbt Fusion (Rust-dvizhok, `dbt --version` -> dbt-fusion).
# On ne podderzhivaet DuckDB: `unknown variant duckdb` pri parse profiles.yml.
# Yavno beryom dbt Core iz .venv. PATH pravim potomu, chto prepare_if_dev()
# zapuskaet `dbt parse` v obkhod DbtCliResource i ishchet dbt v PATH.
DBT_EXECUTABLE = Path(sys.executable).parent / (
    "dbt.exe" if sys.platform == "win32" else "dbt"
)
if DBT_EXECUTABLE.exists():
    os.environ["PATH"] = str(DBT_EXECUTABLE.parent) + os.pathsep + os.environ.get("PATH", "")

DBT_PROJECT_DIR = Path(__file__).parent.parent / "dbt_analytics"
DBT_PROFILES_DIR = Path.home() / ".dbt"

dbt_project = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROFILES_DIR,
)
dbt_project.prepare_if_dev()


class PipelineDbtTranslator(DagsterDbtTranslator):
    """Skleivaet dbt sources s Dagster ingest assetami po AssetKey."""

    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> AssetKey:
        resource_type = dbt_resource_props["resource_type"]
        name = dbt_resource_props["name"]
        if resource_type == "source":
            source_name = dbt_resource_props["source_name"]
            if source_name == "gh_raw":
                # sovpadaet s key= u asseta airbyte_raw_gh_events
                return AssetKey(["raw", name])
        return super().get_asset_key(dbt_resource_props)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    dagster_dbt_translator=PipelineDbtTranslator(),
)
def analytics_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    # dbt build = run + test odnoy komandoy, testy stanovyatsya asset checks
    yield from dbt.cli(["build"], context=context).stream()
'''

CHECKS_PY = '''"""
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
        f.write(entry + "\\n")
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
'''

AIRBYTE_TRIGGER_PY = '''"""
production_pipeline/airbyte_trigger.py
Day 81-85: kak eto vyglyadit s realnym Airbyte (a ne simulyatsiey).

Airbyte OSS API v1: POST /api/v1/connections/sync -> job_id -> polling do success.
Sekrety tolko iz env: AIRBYTE_URL, AIRBYTE_CONNECTION_ID.

V Dagster etot vyzov stavitsya vnutr asseta vmesto sync_partition().
Alternativa - paket dagster-airbyte (pip install dagster-airbyte), on daet
gotovye assety iz Airbyte workspace. Zdes namerenno raw HTTP: menshe zavisimostey
i vidno, chto imenno proiskhodit.
"""

import os
import time

import requests

AIRBYTE_URL = os.environ.get("AIRBYTE_URL", "http://localhost:8000")
CONNECTION_ID = os.environ.get("AIRBYTE_CONNECTION_ID", "")

POLL_SECONDS = 15
TIMEOUT_MINUTES = 60


def trigger_sync(connection_id: str = CONNECTION_ID) -> dict:
    if not connection_id:
        raise RuntimeError("AIRBYTE_CONNECTION_ID is not set")

    resp = requests.post(
        f"{AIRBYTE_URL}/api/v1/connections/sync",
        json={"connectionId": connection_id},
        timeout=30,
    )
    resp.raise_for_status()
    job = resp.json()["job"]
    job_id = job["id"]
    print(f"Airbyte sync started: job {job_id}")

    deadline = time.time() + TIMEOUT_MINUTES * 60
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        status_resp = requests.post(
            f"{AIRBYTE_URL}/api/v1/jobs/get",
            json={"id": job_id},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json()["job"]["status"]
        print(f"  job {job_id}: {status}")
        if status in ("succeeded", "failed", "cancelled"):
            if status != "succeeded":
                raise RuntimeError(f"Airbyte job {job_id} finished as {status}")
            return status_resp.json()["job"]

    raise TimeoutError(f"Airbyte job {job_id} did not finish in {TIMEOUT_MINUTES}m")


if __name__ == "__main__":
    trigger_sync()
'''

DEFINITIONS_PY = '''"""
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
'''

PYPROJECT_TOML = """[tool.dagster]
module_name = "definitions"
"""

PIPELINE_README = """# production_pipeline - Days 81-85

Первый сквозной production pipeline: **Airbyte -> raw -> dbt -> marts**,
оркестрация в Dagster, дневные партиции, quality gate.

## Граф

```
raw/airbyte_raw_gh_events   (Airbyte sync, 1 партиция = 1 сутки)
        |
        v
stg_gh_events               (dbt view: JSON -> колонки, дедупликация)
        |
        +--> mart_daily_events    (dbt incremental, delete+insert по дате)
        +--> mart_repo_activity   (dbt table)
```

## Файлы

| Файл | Что делает |
|---|---|
| `ingest_core.py` | функция `sync_partition` — идемпотентная загрузка одной партиции в raw |
| `assets_ingest.py` | Dagster asset поверх неё, `DailyPartitionsDefinition` |
| `assets_dbt.py` | `@dbt_assets` + translator, склеивающий dbt source с ingest-ассетом |
| `checks.py` | asset checks: raw не пустая, freshness <= 26h, alert в `alerts.log` |
| `airbyte_trigger.py` | production-вариант: реальный вызов Airbyte API |
| `definitions.py` | `Definitions` + job + schedule 05:00 UTC |

## Запуск

```powershell
# 1. Данные + первый прогон end-to-end
python lesson81_85.py

# 2. Dagster UI
cd production_pipeline
dagster dev -f definitions.py
# localhost:3000 -> Assets -> Materialize -> выбрать партицию
# Backfill: выделить диапазон дат -> Launch backfill

# 3. Только dbt
cd dbt_analytics
dbt build --select tag:production_pipeline
dbt source freshness --select source:gh_raw
```

## Переключение на Snowflake

`ingest_core.py` пишет в DuckDB через `dbt_analytics/analytics.duckdb`.
Для Snowflake: заменить `sync_partition` на `airbyte_trigger.trigger_sync`,
в `profiles.yml` выбрать target `snowflake_dev`, в `sources_gh.yml` указать
`database: analytics_db`. Модели staging/marts менять не нужно, кроме
JSON-синтаксиса: DuckDB `json_extract_string(col, '$.f')` -> Snowflake `col:f::TYPE`.
"""

# ==========================================================================
# 2. dbt modeli
# ==========================================================================

SOURCES_GH_YML = """version: 2

sources:
  - name: gh_raw
    description: "GitHub Events, zagruzhennye Airbyte v raw schema"
    schema: raw
    loaded_at_field: _airbyte_extracted_at
    freshness:
      warn_after: {count: 26, period: hour}
      error_after: {count: 48, period: hour}
    tables:
      - name: airbyte_raw_gh_events
        description: "Syrye sobytiya: _airbyte_data JSON + meta kolonki"
"""

STG_GH_EVENTS_SQL = """-- models/staging/stg_gh_events.sql
-- Day 81-85: normalizatsiya Airbyte raw -> tipizirovannye kolonki
-- [[Airbyte]] [[dbt]] [[Dagster]]
--
-- Snowflake variant togo zhe izvlecheniya:
--   _airbyte_data:event_id::VARCHAR AS event_id

{{
    config(materialized='view', tags=['production_pipeline', 'staging'])
}}

WITH raw AS (
    SELECT
        json_extract_string(_airbyte_data, '$.event_id')        AS event_id,
        json_extract_string(_airbyte_data, '$.event_type')      AS event_type,
        json_extract_string(_airbyte_data, '$.actor')           AS actor_login,
        json_extract_string(_airbyte_data, '$.repo')            AS repo_name,
        CAST(json_extract_string(_airbyte_data, '$.created_at')
             AS TIMESTAMP)                                      AS created_at,
        CAST(json_extract_string(_airbyte_data, '$.payload_size')
             AS INTEGER)                                        AS payload_size,
        _airbyte_partition_date                                 AS event_date,
        _airbyte_extracted_at                                   AS airbyte_extracted_at
    FROM {{ source('gh_raw', 'airbyte_raw_gh_events') }}
    WHERE _airbyte_data IS NOT NULL
)

SELECT
    event_id,
    event_type,
    LOWER(actor_login) AS actor_login,
    repo_name,
    created_at,
    payload_size,
    event_date,
    airbyte_extracted_at
FROM raw
WHERE event_id IS NOT NULL
  AND payload_size > 0
-- Airbyte mozhet dostavit odnu stroku dvazhdy: beryom samuyu svezhuyu
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY event_id ORDER BY airbyte_extracted_at DESC
) = 1
"""

MART_DAILY_EVENTS_SQL = """-- models/marts/mart_daily_events.sql
-- Day 81-85: inkrementalnyy mart po dnyam
-- DuckDB ne umeet MERGE bez PK -> strategiya delete+insert

{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='event_date',
        tags=['production_pipeline', 'marts']
    )
}}

SELECT
    event_date,
    COUNT(*)                                                   AS events,
    COUNT(DISTINCT actor_login)                                AS active_actors,
    COUNT(DISTINCT repo_name)                                  AS active_repos,
    SUM(CASE WHEN event_type = 'PushEvent' THEN 1 ELSE 0 END)  AS pushes,
    SUM(CASE WHEN event_type = 'PullRequestEvent'
             THEN 1 ELSE 0 END)                                AS pull_requests,
    SUM(CASE WHEN event_type = 'WatchEvent' THEN 1 ELSE 0 END) AS stars,
    ROUND(AVG(payload_size), 1)                                AS avg_payload_size
FROM {{ ref('stg_gh_events') }}

{% if is_incremental() %}
-- Perechityvaem tolko svezhie partitsii, a ne vsyu istoriyu
WHERE event_date >= (SELECT COALESCE(MAX(event_date), '1970-01-01') FROM {{ this }})
{% endif %}

GROUP BY event_date
"""

MART_REPO_ACTIVITY_SQL = """-- models/marts/mart_repo_activity.sql
-- Day 81-85: aktivnost po repozitoriyam za vsyu istoriyu

{{
    config(materialized='table', tags=['production_pipeline', 'marts'])
}}

WITH events AS (
    SELECT * FROM {{ ref('stg_gh_events') }}
)

SELECT
    repo_name,
    COUNT(*)                                                   AS events,
    COUNT(DISTINCT actor_login)                                AS contributors,
    COUNT(DISTINCT event_date)                                 AS active_days,
    SUM(CASE WHEN event_type = 'PushEvent' THEN 1 ELSE 0 END)  AS pushes,
    SUM(CASE WHEN event_type = 'PullRequestEvent'
             THEN 1 ELSE 0 END)                                AS pull_requests,
    MIN(event_date)                                            AS first_event_date,
    MAX(event_date)                                            AS last_event_date,
    ROUND(
        COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT event_date), 0), 2
    )                                                          AS events_per_day
FROM events
GROUP BY repo_name
"""

SCHEMA_PRODUCTION_YML = """version: 2

models:
  - name: stg_gh_events
    description: "Normalizovannye GitHub Events iz Airbyte raw"
    columns:
      - name: event_id
        description: "Unikalnyy ID sobytiya v GitHub"
        tests: [unique, not_null]
      - name: event_type
        tests:
          - not_null
          - accepted_values:
              values: ['PushEvent', 'PullRequestEvent', 'IssuesEvent',
                       'WatchEvent', 'ForkEvent']
      - name: actor_login
        tests: [not_null]
      - name: repo_name
        tests: [not_null]
      - name: event_date
        tests: [not_null]

  - name: mart_daily_events
    description: "Inkrementalnyy mart: aktivnost po dnyam"
    columns:
      - name: event_date
        tests: [unique, not_null]
      - name: events
        tests: [not_null]

  - name: mart_repo_activity
    description: "Aktivnost po repozitoriyam"
    columns:
      - name: repo_name
        tests: [unique, not_null]
      - name: contributors
        tests: [not_null]
"""


# ==========================================================================
# Shagi
# ==========================================================================


def step1_scaffold_pipeline() -> None:
    banner("STEP 1", "Sozdanie paketa production_pipeline/")

    write_utf8(PIPELINE_DIR / "ingest_core.py", INGEST_CORE_PY)
    write_utf8(
        PIPELINE_DIR / "assets_ingest.py",
        ASSETS_INGEST_PY.replace("__PARTITION_START__", PARTITION_START),
    )
    write_utf8(PIPELINE_DIR / "assets_dbt.py", ASSETS_DBT_PY)
    write_utf8(PIPELINE_DIR / "checks.py", CHECKS_PY)
    write_utf8(PIPELINE_DIR / "airbyte_trigger.py", AIRBYTE_TRIGGER_PY)
    write_utf8(PIPELINE_DIR / "definitions.py", DEFINITIONS_PY)
    write_utf8(PIPELINE_DIR / "pyproject.toml", PYPROJECT_TOML)
    write_utf8(PIPELINE_DIR / "README.md", PIPELINE_README)

    print("\n  Proverka sintaksisa sgenerirovannykh .py:")
    import py_compile

    for py in sorted(PIPELINE_DIR.glob("*.py")):
        py_compile.compile(str(py), doraise=True)
        print(f"    OK {py.name}")


def step2_write_dbt_models() -> None:
    banner("STEP 2", "dbt modeli: staging + 2 marts + testy")

    write_utf8(DBT_PROJECT / "models" / "staging" / "sources_gh.yml", SOURCES_GH_YML)
    write_utf8(
        DBT_PROJECT / "models" / "staging" / "stg_gh_events.sql", STG_GH_EVENTS_SQL
    )
    write_utf8(
        DBT_PROJECT / "models" / "marts" / "mart_daily_events.sql",
        MART_DAILY_EVENTS_SQL,
    )
    write_utf8(
        DBT_PROJECT / "models" / "marts" / "mart_repo_activity.sql",
        MART_REPO_ACTIVITY_SQL,
    )
    write_utf8(
        DBT_PROJECT / "models" / "schema_production.yml", SCHEMA_PRODUCTION_YML
    )


def step3_generate_source_data() -> None:
    banner("STEP 3", "Datasset GitHub Events (format GH Archive)")

    csv_path = SOURCE_DIR / "gh_events.csv"
    rows = []
    counter = 1

    for pdate in PARTITIONS:
        n = random.randint(40, 80)
        for _ in range(n):
            hour = random.randint(0, 23)
            minute = random.randint(0, 59)
            rows.append(
                {
                    "event_id": f"E{counter:07d}",
                    "event_type": random.choices(
                        EVENT_TYPES, weights=[50, 20, 15, 10, 5]
                    )[0],
                    "actor": random.choice(ACTORS),
                    "repo": random.choice(REPOS),
                    "created_at": f"{pdate} {hour:02d}:{minute:02d}:00",
                    "payload_size": random.randint(120, 8000),
                    "event_date": pdate,
                }
            )
            counter += 1

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"  OK {csv_path.relative_to(PROJECT_ROOT)}: {len(rows)} sobytiy")
    for pdate in PARTITIONS:
        cnt = sum(1 for r in rows if r["event_date"] == pdate)
        print(f"    {pdate}: {cnt} sobytiy")


def _load_ingest_core():
    """Importiruem tolko chto sozdannyy modul po puti."""
    spec = importlib.util.spec_from_file_location(
        "ingest_core", PIPELINE_DIR / "ingest_core.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["ingest_core"] = module
    spec.loader.exec_module(module)
    return module


def step4_airbyte_sync() -> list:
    banner("STEP 4", "Airbyte sync po partitsiyam -> raw schema")

    ingest = _load_ingest_core()
    csv_path = SOURCE_DIR / "gh_events.csv"
    results = []

    for pdate in PARTITIONS:
        res = ingest.sync_partition(DBT_DB, csv_path, pdate)
        results.append(res)
        print(
            f"  {pdate}: synced {res['rows_synced']:>3}  "
            f"total in raw {res['rows_total']:>4}"
        )

    # Idempotentnost: povtor toy zhe partitsii ne dolzhen razdut tablitsu
    before = results[-1]["rows_total"]
    again = ingest.sync_partition(DBT_DB, csv_path, PARTITIONS[-1])
    print(
        f"\n  Povtornyy sync {PARTITIONS[-1]}: bylo {before}, "
        f"stalo {again['rows_total']} "
        f"({'idempotentno OK' if before == again['rows_total'] else 'DUBLI!'})"
    )
    return results


def _run_dbt(args: list) -> tuple:
    """Zapuskaet dbt iz tekushchego venv. Vozvrashchaet (rc, output).

    Beryom dbt.exe ryadom s interpretatorom, a ne `python -m dbt.cli.main`:
    vtoroy variant daet RuntimeWarning 'found in sys.modules after import'.
    """
    dbt_exe = Path(sys.executable).parent / ("dbt.exe" if sys.platform == "win32" else "dbt")
    cmd = [str(dbt_exe)] + args if dbt_exe.exists() else [sys.executable, "-m", "dbt.cli.main"] + args
    proc = subprocess.run(
        cmd,
        cwd=str(DBT_PROJECT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def step5_dbt_build() -> dict:
    banner("STEP 5", "dbt build: run + test na tag:production_pipeline")

    rc, out = _run_dbt(["build", "--select", "tag:production_pipeline"])
    tail = [ln for ln in out.splitlines() if ln.strip()][-18:]
    for ln in tail:
        print("   ", ln)

    if rc != 0:
        print("\n  dbt build FAILED (rc={})".format(rc))
    else:
        print("\n  OK dbt build passed")

    rc_fresh, out_fresh = _run_dbt(
        ["source", "freshness", "--select", "source:gh_raw"]
    )
    fresh_tail = [ln for ln in out_fresh.splitlines() if ln.strip()][-6:]
    print("\n  source freshness:")
    for ln in fresh_tail:
        print("   ", ln)

    return {"build_rc": rc, "freshness_rc": rc_fresh, "build_output": out}


def step6_quality_gate(build: dict) -> list:
    banner("STEP 6", "Quality gate + alert")

    con = duckdb.connect(str(DBT_DB), read_only=True)
    checks = []
    try:
        raw_rows = con.execute(
            "SELECT COUNT(*) FROM raw.airbyte_raw_gh_events"
        ).fetchone()[0]
        checks.append(("raw_not_empty", raw_rows > 0, f"rows={raw_rows}"))

        last_sync = con.execute(
            "SELECT MAX(_airbyte_extracted_at) FROM raw.airbyte_raw_gh_events"
        ).fetchone()[0]
        age_h = (datetime.now() - last_sync).total_seconds() / 3600
        checks.append(
            ("raw_freshness_26h", age_h <= 26, f"age={age_h:.2f}h")
        )

        stg_rows = con.execute("SELECT COUNT(*) FROM main.stg_gh_events").fetchone()[0]
        dupes = con.execute(
            "SELECT COUNT(*) FROM (SELECT event_id FROM main.stg_gh_events "
            "GROUP BY event_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        checks.append(("stg_event_id_unique", dupes == 0, f"dupes={dupes}"))

        mart_days = con.execute(
            "SELECT COUNT(*) FROM main.mart_daily_events"
        ).fetchone()[0]
        checks.append(
            (
                "mart_covers_all_partitions",
                mart_days >= len(PARTITIONS),
                f"days={mart_days}, expected>={len(PARTITIONS)}",
            )
        )

        orphans = con.execute(
            "SELECT COUNT(*) FROM main.mart_repo_activity m "
            "LEFT JOIN (SELECT DISTINCT repo_name FROM main.stg_gh_events) s "
            "ON m.repo_name = s.repo_name WHERE s.repo_name IS NULL"
        ).fetchone()[0]
        checks.append(("mart_no_orphan_repos", orphans == 0, f"orphans={orphans}"))

        checks.append(
            ("dbt_build_green", build["build_rc"] == 0, f"rc={build['build_rc']}")
        )
    finally:
        con.close()

    print()
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name:<28} {detail}")

    failed = [c for c in checks if not c[1]]
    if failed:
        alerts_log = PIPELINE_DIR / "alerts.log"
        with open(alerts_log, "a", encoding="utf-8") as f:
            for name, _, detail in failed:
                f.write(
                    f"[{datetime.now().isoformat(timespec='seconds')}] "
                    f"[ERROR] quality gate failed: {name} ({detail})\n"
                )
        print(f"\n  {len(failed)} check(s) FAILED -> alert v production_pipeline/alerts.log")
    else:
        print("\n  OK quality gate: vse proverki zelenye")

    return checks


def step7_reports(sync_results: list, checks: list) -> None:
    banner("STEP 7", "Otchety v reports/")

    stamp = TODAY.isoformat()

    pd.DataFrame(sync_results).to_csv(
        REPORTS_DIR / f"day81_85_sync_log_{stamp}.csv", index=False
    )
    print(f"  OK reports/day81_85_sync_log_{stamp}.csv")

    pd.DataFrame(
        [{"check": n, "passed": p, "detail": d} for n, p, d in checks]
    ).to_csv(REPORTS_DIR / f"day81_85_quality_gate_{stamp}.csv", index=False)
    print(f"  OK reports/day81_85_quality_gate_{stamp}.csv")

    con = duckdb.connect(str(DBT_DB), read_only=True)
    try:
        daily = con.execute(
            "SELECT * FROM main.mart_daily_events ORDER BY event_date"
        ).df()
        repos = con.execute(
            "SELECT * FROM main.mart_repo_activity ORDER BY events DESC"
        ).df()
    finally:
        con.close()

    daily.to_csv(REPORTS_DIR / f"day81_85_mart_daily_events_{stamp}.csv", index=False)
    repos.to_csv(REPORTS_DIR / f"day81_85_mart_repo_activity_{stamp}.csv", index=False)
    print(f"  OK reports/day81_85_mart_daily_events_{stamp}.csv")
    print(f"  OK reports/day81_85_mart_repo_activity_{stamp}.csv")

    print("\n  mart_daily_events:")
    print(daily.to_string(index=False))
    print("\n  mart_repo_activity:")
    print(repos.to_string(index=False))


def main() -> None:
    print("=" * 60)
    print("  Days 81-85: Production Pipeline")
    print("  Airbyte -> raw -> dbt -> marts, orchestrated by Dagster")
    print("=" * 60)

    step1_scaffold_pipeline()
    step2_write_dbt_models()
    step3_generate_source_data()
    sync_results = step4_airbyte_sync()
    build = step5_dbt_build()
    checks = step6_quality_gate(build)
    step7_reports(sync_results, checks)

    print("\n" + "=" * 60)
    print("  ALL DONE!")
    print("=" * 60)
    print(
        """
Next steps:
  1. Dagster UI - posmotret skvoznoy graf i partitsii:
       cd production_pipeline
       dagster dev -f definitions.py
       # localhost:3000 -> Assets -> Materialize -> vybrat partitsiyu
       # Backfill: vydelit diapazon dat -> Launch backfill
  2. Proverit, chto dbt source svyazan s ingest assetom:
       v grafe raw/airbyte_raw_gh_events -> stg_gh_events (odna strelka, ne dva grafa)
  3. Slomat pipeline namerenno i posmotret alert:
       udalit stroki iz raw -> zapustit shag quality gate zanovo
  4. Snowflake: sm. production_pipeline/README.md, razdel pro Snowflake

Git:
  git add production_pipeline/ dbt_analytics/models/ lesson81_85.py
  git commit -m "feat: Days 81-85 production pipeline Airbyte -> dbt -> marts on Dagster"
  git push origin main
"""
    )


if __name__ == "__main__":
    main()
