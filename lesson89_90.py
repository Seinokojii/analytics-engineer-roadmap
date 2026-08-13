#!/usr/bin/env python3
"""
lesson89_90.py — Days 89-90: Документация + GitHub

Запуск:
    python lesson89_90.py

Закрывает неделю 12 и Месяц 3. Продолжает дни 81-88.

Что делает:
  1. Аудит покрытия описаниями до правок (manifest.json)
  2. schema_production.yml: описание каждой колонки + все тесты Day 86-88
  3. dbt docs generate -> catalog.json, покрытие после
  4. Каталог ассетов Dagster -> CSV
  5. README.md: Mermaid-диаграмма + инструкции запуска + CI badge
  6. docs/DEMO_SCRIPT.md — сценарий 2-минутного видео с таймингами
  7. Отчёт в reports/

Почему артефакты на английском:
  README, описания моделей и сценарий демо — это портфолио, которое
  читает рекрутер и hiring manager в EU/US. Цель roadmap — remote
  global. Код и комментарии — на русском, они для тебя.

Порядок важен:
  Этот скрипт перезаписывает schema_production.yml и является
  последней инстанцией для него. Если после него запустить
  lesson86_88.py, описания колонок пропадут (там версия без них) —
  тогда просто запустить lesson89_90.py снова.
"""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT = PROJECT_ROOT / "dbt_analytics"
PIPELINE_DIR = PROJECT_ROOT / "production_pipeline"
REPORTS_DIR = PROJECT_ROOT / "reports"
DOCS_DIR = PROJECT_ROOT / "docs"

REPORTS_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)

SCHEMA_YML = DBT_PROJECT / "models" / "schema_production.yml"
MANIFEST = DBT_PROJECT / "target" / "manifest.json"
CATALOG = DBT_PROJECT / "target" / "catalog.json"

GITHUB_USER = "Seinokojii"
GITHUB_REPO = "analytics-engineer-roadmap"

PROD_MODELS = ["stg_gh_events", "mart_daily_events", "mart_repo_activity"]

SEP = "=" * 62


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def venv_python() -> Path:
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return PROJECT_ROOT / ".venv" / rel


def ensure_venv() -> None:
    """Перезапускает скрипт в .venv. См. lesson86_88.py — та же ловушка:
    глобальный Python несёт нерабочий dbt."""
    if os.environ.get("AE_LESSON_REEXEC") == "1":
        return
    vpy = venv_python()
    if not vpy.exists():
        print("  ! .venv не найден — работаю текущим интерпретатором")
        return
    if Path(sys.executable).resolve() == vpy.resolve():
        return
    print(f"  Запущено не из .venv: {sys.executable}")
    print(f"  Перезапуск в:            {vpy}")
    sys.stdout.flush()
    env = dict(os.environ, AE_LESSON_REEXEC="1")
    proc = subprocess.run(
        [str(vpy), str(Path(__file__).resolve()), *sys.argv[1:]], env=env
    )
    sys.exit(proc.returncode)


def dbt_cmd() -> list:
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    return [str(exe)] if exe.exists() else [sys.executable, "-m", "dbt.cli.main"]


def run_dbt(args: list, allow_fail: bool = False) -> tuple:
    cmd = dbt_cmd() + args
    print(f"  $ dbt {' '.join(args)}")
    proc = subprocess.run(
        cmd, cwd=str(DBT_PROJECT), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not allow_fail:
        print("\n".join(out.strip().splitlines()[-25:]))
        raise RuntimeError(f"dbt {' '.join(args)} failed (rc={proc.returncode})")
    return proc.returncode, out


def dbt_summary(out: str) -> str:
    for line in reversed(out.splitlines()):
        if "Done." in line and "PASS=" in line:
            return line.split("Done.")[-1].strip()
    return "no summary line"


# --------------------------------------------------------------------------
# STEP 1 — аудит
# --------------------------------------------------------------------------
def coverage_from_manifest() -> dict:
    """Сколько колонок production-моделей имеют description."""
    if not MANIFEST.exists():
        return {}
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = {}
    for node in man["nodes"].values():
        if node.get("resource_type") != "model":
            continue
        if node.get("name") not in PROD_MODELS:
            continue
        cols = node.get("columns", {})
        result[node["name"]] = {
            "model_described": bool((node.get("description") or "").strip()),
            "columns_documented": len(cols),
            "columns_with_desc": sum(
                1 for c in cols.values() if (c.get("description") or "").strip()
            ),
        }
    return result


def print_coverage(cov: dict, label: str) -> None:
    print(f"\n  {label}")
    print(f"  {'model':<22} {'model desc':<12} {'cols':<7} {'with desc'}")
    print("  " + "-" * 52)
    for name in PROD_MODELS:
        info = cov.get(name)
        if not info:
            print(f"  {name:<22} {'?':<12} {'?':<7} ?")
            continue
        print(
            f"  {name:<22} {str(info['model_described']):<12} "
            f"{info['columns_documented']:<7} {info['columns_with_desc']}"
        )


def step1_audit():
    banner("STEP 1", "Аудит: что задокументировано до правок")
    print("  dbt docs строится из manifest.json. Чего нет в schema.yml —")
    print("  того не будет и в документации, даже если колонка есть в БД.")
    cov = coverage_from_manifest()
    print_coverage(cov, "ДО:")
    return cov


# --------------------------------------------------------------------------
# STEP 2 — полные описания
# --------------------------------------------------------------------------
SCHEMA_DOCUMENTED = '''version: 2

# Days 89-90: Documentation.
# Этот файл — последняя инстанция для production-моделей.
# Содержит все тесты Day 86-88 ПЛЮС описание каждой колонки.
#
# Три уровня проверок:
#   1. dbt core        - unique / not_null / accepted_values
#   2. dbt-expectations — диапазоны, форматы, сравнение колонок
#   3. elementary       — аномалии во времени

models:
  - name: stg_gh_events
    description: >
      Typed GitHub event stream. Flattens the Airbyte raw JSON payload into
      columns, drops rows with no event id or non-positive payload size, and
      de-duplicates by event id keeping the latest extraction. One row per
      GitHub event. Materialized as a view: the cost is in the marts, not here.
    config:
      elementary:
        timestamp_column: "created_at"
    tests:
      - elementary.volume_anomalies:
          time_bucket:
            period: day
            count: 1
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
    columns:
      - name: event_id
        description: >
          GitHub's own event identifier. Primary key of this model. Airbyte can
          deliver the same event twice, so the model de-duplicates on this
          column before the uniqueness test runs.
        tests: [unique, not_null]
      - name: event_type
        description: >
          Kind of GitHub activity. Constrained to the five types this pipeline
          supports; anything else means the upstream schema changed and the
          accepted_values test is expected to catch it.
        tests:
          - not_null
          - accepted_values:
              values: ['PushEvent', 'PullRequestEvent', 'IssuesEvent',
                       'WatchEvent', 'ForkEvent']
      - name: actor_login
        description: >
          GitHub username that triggered the event, lower-cased so that counts
          of distinct actors are not split by letter case.
        tests:
          - not_null
          - dbt_expectations.expect_column_values_to_match_regex:
              regex: "^[^A-Z]*$"
      - name: repo_name
        description: "Repository the event belongs to, in owner/name form."
        tests: [not_null]
      - name: created_at
        description: >
          Event timestamp reported by GitHub. Used by Elementary as the time
          axis for anomaly detection.
      - name: payload_size
        description: >
          Size of the event payload in bytes. Rows with a non-positive size are
          filtered out upstream; the upper bound guards against source garbage.
        tests:
          - not_null
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 1
              max_value: 100000
      - name: event_date
        description: >
          Partition date assigned by the ingest layer. This is the grain the
          Dagster daily partition and the incremental mart are keyed on.
        tests: [not_null]
      - name: airbyte_extracted_at
        description: >
          Extraction timestamp written by the loader. Drives source freshness
          and decides which duplicate wins.

  - name: mart_daily_events
    description: >
      Daily activity roll-up, one row per calendar day. Incremental with a
      delete+insert strategy keyed on event_date, so re-running a day is
      idempotent - the standard workaround for engines without MERGE.
    config:
      elementary:
        timestamp_column: "event_date"
    tests:
      - elementary.volume_anomalies:
          time_bucket:
            period: day
            count: 1
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
      - dbt_expectations.expect_column_pair_values_A_to_be_greater_than_B:
          column_A: events
          column_B: active_actors
          or_equal: true
    columns:
      - name: event_date
        description: "Calendar day. Grain and unique key of this model."
        tests: [unique, not_null]
      - name: events
        description: "Total events on that day."
        tests:
          - not_null
          - elementary.column_anomalies:
              column_anomalies: [null_count, average, max]
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 1
      - name: active_actors
        description: >
          Distinct users active that day. Can never exceed the event count -
          a pair test enforces it, because a breach means a fan-out join.
        tests:
          - not_null
          - elementary.column_anomalies:
              column_anomalies: [null_count, average]
      - name: active_repos
        description: "Distinct repositories touched that day."
        tests: [not_null]
      - name: pushes
        description: "Events of type PushEvent."
      - name: pull_requests
        description: "Events of type PullRequestEvent."
      - name: stars
        description: "Events of type WatchEvent - GitHub reports a star as a watch."
      - name: avg_payload_size
        description: "Mean payload size in bytes for that day, rounded to 0.1."

  - name: mart_repo_activity
    description: >
      Per-repository activity over the full loaded history. Full-refresh table:
      the aggregate spans all days, so there is no correct incremental window.
    tests:
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
      - dbt_expectations.expect_column_pair_values_A_to_be_greater_than_B:
          column_A: events
          column_B: contributors
          or_equal: true
    columns:
      - name: repo_name
        description: "Repository in owner/name form. Grain of this model."
        tests: [unique, not_null]
      - name: events
        description: "Total events recorded for the repository."
      - name: contributors
        description: "Distinct actors seen in the repository."
        tests:
          - not_null
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 1
      - name: active_days
        description: "Number of distinct days with at least one event."
      - name: pushes
        description: "Events of type PushEvent."
      - name: pull_requests
        description: "Events of type PullRequestEvent."
      - name: first_event_date
        description: "Earliest event date currently loaded for the repository."
      - name: last_event_date
        description: >
          Latest event date currently loaded. Compare against today to spot a
          repository that went quiet.
      - name: events_per_day
        description: >
          Events divided by active days. Intensity while active - not an
          average over the calendar, which is why a quiet repo does not dilute it.
        tests:
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 0
'''


def step2_descriptions():
    banner("STEP 2", "Описание каждой колонки в schema_production.yml")
    SCHEMA_YML.write_text(SCHEMA_DOCUMENTED, encoding="utf-8")
    n_desc = SCHEMA_DOCUMENTED.count("description:")
    n_tests = (
        SCHEMA_DOCUMENTED.count("dbt_expectations.")
        + SCHEMA_DOCUMENTED.count("elementary.")
    )
    print(f"  записан {SCHEMA_YML.relative_to(PROJECT_ROOT)}")
    print(f"  description: {n_desc}")
    print(f"  тестов dbt-expectations + elementary сохранено: {n_tests}")
    print("  важно: тесты Day 86-88 должны выжить — проверяем в STEP 3")


# --------------------------------------------------------------------------
# STEP 3 — dbt docs
# --------------------------------------------------------------------------
def step3_dbt_docs(cov_before: dict):
    banner("STEP 3", "dbt docs generate")

    print("\n  3.1 build — убеждаемся, что тесты не потерялись")
    rc, out = run_dbt(["build", "--select", "tag:production_pipeline"],
                      allow_fail=True)
    summary = dbt_summary(out)
    print(f"    {summary}")
    if "ERROR=0" not in summary:
        print("    ! тесты не зелёные — документация подождёт")

    print("\n  3.2 docs generate")
    run_dbt(["docs", "generate"])

    cov_after = coverage_from_manifest()
    print_coverage(cov_before, "ДО:")
    print_coverage(cov_after, "ПОСЛЕ:")

    total_before = sum(c["columns_with_desc"] for c in cov_before.values())
    total_after = sum(c["columns_with_desc"] for c in cov_after.values())
    print(f"\n  колонок с описанием: {total_before} -> {total_after}")

    if CATALOG.exists():
        cat = json.loads(CATALOG.read_text(encoding="utf-8"))
        in_db = {}
        for node in cat.get("nodes", {}).values():
            nm = node["metadata"]["name"]
            if nm in PROD_MODELS:
                in_db[nm] = len(node.get("columns", {}))
        print("\n  колонок в БД по catalog.json:")
        for nm in PROD_MODELS:
            documented = cov_after.get(nm, {}).get("columns_with_desc", 0)
            actual = in_db.get(nm, 0)
            mark = "OK" if actual and documented >= actual else "!"
            print(f"    {mark} {nm:<22} {documented}/{actual}")

    print("\n  Посмотреть: cd dbt_analytics && dbt docs serve --port 8080")
    return summary, cov_after


# --------------------------------------------------------------------------
# STEP 4 — каталог ассетов Dagster
# --------------------------------------------------------------------------
def step4_dagster_catalog():
    banner("STEP 4", "Dagster asset catalog")

    sys.path.insert(0, str(PIPELINE_DIR))
    os.environ.setdefault("DAGSTER_HOME", str(PROJECT_ROOT / "dagster_home"))
    try:
        from definitions import defs
    except Exception as e:
        print(f"  ! не удалось загрузить definitions.py: {e}")
        return []

    rows = []
    for a in defs.assets:
        descriptions = getattr(a, "descriptions_by_key", {}) or {}
        for key in getattr(a, "keys", []) or []:
            name = key.to_user_string()
            desc = (descriptions.get(key) or "").strip()
            # dbt-ассеты получают description из schema.yml, и туда же
            # dbt кладёт весь Raw SQL — берём только первую строку.
            short = desc.split("\n")[0][:110]
            rows.append({"type": "asset", "name": name, "description": short})

    for c in defs.asset_checks or []:
        for key in getattr(c, "check_keys", []) or []:
            rows.append({
                "type": "asset_check",
                "name": f"{key.asset_key.to_user_string()}:{key.name}",
                "description": "",
            })

    for j in defs.jobs or []:
        rows.append({"type": "job", "name": j.name,
                     "description": (getattr(j, "description", "") or "")})
    for s in defs.schedules or []:
        rows.append({"type": "schedule", "name": s.name,
                     "description": f"cron: {s.cron_schedule}"})

    ours = [r for r in rows if not r["name"].startswith("elementary/")]
    undocumented = [
        r for r in ours if r["type"] == "asset" and not r["description"]
    ]

    print(f"  всего в каталоге: {len(rows)}")
    print(f"  из них служебных elementary/: {len(rows) - len(ours)}")
    print(f"  наших: {len(ours)}")
    print(f"  assets без описания: {len(undocumented)}")

    print("\n  Production pipeline:")
    for r in ours:
        if r["type"] in ("asset", "asset_check") and (
            "gh_events" in r["name"]
            or r["name"] in ("mart_daily_events", "mart_repo_activity")
        ):
            print(f"    [{r['type']:<11}] {r['name']}")

    out = REPORTS_DIR / "day89_90_dagster_catalog.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["type", "name", "description"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n  OK: {out.relative_to(PROJECT_ROOT)}")
    return rows


# --------------------------------------------------------------------------
# STEP 5 — README
# --------------------------------------------------------------------------
README = """# Production Analytics Pipeline

[![dbt CI](https://github.com/{user}/{repo}/actions/workflows/dbt_ci.yml/badge.svg)](https://github.com/{user}/{repo}/actions/workflows/dbt_ci.yml)

An end-to-end analytics pipeline: ingestion, warehouse modelling,
orchestration and three layers of data quality checks - all reproducible
from a clean checkout.

Built on **dbt + Dagster + DuckDB** locally, designed to move to
**Snowflake** by changing a target in `profiles.yml`.

---

## Architecture

```mermaid
flowchart LR
    CSV["gh_events.csv<br/>source system"]

    subgraph INGEST["Ingest - Airbyte pattern"]
        RAW[("raw.airbyte_raw_gh_events<br/>JSON payload + metadata")]
    end

    subgraph TRANSFORM["dbt"]
        STG["stg_gh_events<br/>view<br/>flatten - filter - dedupe"]
        M1["mart_daily_events<br/>incremental<br/>delete+insert by date"]
        M2["mart_repo_activity<br/>table"]
    end

    subgraph QUALITY["Quality"]
        AC["Dagster asset checks<br/>not empty - freshness"]
        T["26 dbt tests<br/>16 core + 10 expectations"]
        EL["Elementary<br/>4 anomaly tests, 7 metrics"]
    end

    DOCS["dbt docs<br/>Dagster asset catalog"]

    CSV --> RAW --> STG
    STG --> M1
    STG --> M2
    RAW -.-> AC
    M1 -.-> T
    M2 -.-> T
    M1 -.-> EL
    STG -.-> EL
    M1 --> DOCS
    M2 --> DOCS
```

Dagster orchestrates the whole graph. The ingest asset is partitioned by day,
so a backfill re-runs one partition at a time and every re-run is idempotent.

---

## Quick start

Requires Python 3.12. Python 3.14 is **not** supported - dbt's dependencies
break on it.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -r requirements.txt

python lesson81_85.py           # load data, run the pipeline end to end
python lesson86_88.py           # tests, monitoring, CI, Docker
python lesson89_90.py           # documentation
```

Dagster UI:

```bash
cd production_pipeline
dagster dev -f definitions.py   # http://localhost:3000
```

Model documentation:

```bash
cd dbt_analytics
dbt docs generate && dbt docs serve --port 8080
```

dbt only:

```bash
cd dbt_analytics
dbt build --select tag:production_pipeline
dbt source freshness --select source:gh_raw
```

Docker:

```bash
docker compose up               # Dagster on :3000
docker compose --profile docs up dbt-docs
```

---

## Data quality

30 tests run on every build, in three layers, each catching what the others
miss:

| Layer | Answers | Example |
|---|---|---|
| dbt core tests | Is this row valid? | `unique`, `not_null`, `accepted_values` |
| dbt-expectations | Is this value plausible? | row count > 0, payload size in range |
| Elementary | Does today look like yesterday? | volume drop, mean shift, null spike |
| Dagster asset checks | Should downstream even run? | raw not empty, source fresh < 26h |

The suite is verified negatively: `lesson86_88.py` step 9 corrupts the raw
table on purpose, asserts the tests go red, then restores the database.
A test suite that has never failed is an unverified test suite.

---

## CI

`.github/workflows/dbt_ci.yml` runs on every pull request:

1. **parse + compile** - catches broken Jinja and bad `ref()` without touching
   data. Fails in under a minute.
2. **build + test** - rebuilds the warehouse from CSV on a clean DuckDB file
   and runs the full test suite.

The database is gitignored, so CI reconstructs `raw` using the same
`ingest_core.sync_partition` the Dagster asset calls. One ingestion code path
for local, CI and production - a difference there is how green CI hides a
broken pipeline.

---

## Moving to Snowflake

The warehouse is swappable by design:

1. Point a `prod` target at Snowflake in `profiles.yml`
2. Put credentials in GitHub Secrets (`SNOWFLAKE_ACCOUNT`, `_USER`, ...)
3. Uncomment the `dbt-snowflake` job in `dbt_ci.yml`
4. Delete `macros/duckdb_elementary_shims.sql` - it exists only because
   Elementary ships no DuckDB implementation of `edr_multi_value_in`

Model SQL needs one change: DuckDB's `json_extract_string(col, '$.field')`
becomes Snowflake's `col:field::TYPE`.

---

## Layout

| Path | Contents |
|---|---|
| `production_pipeline/` | Dagster assets, checks, schedule |
| `dbt_analytics/` | dbt models, tests, macros |
| `.github/workflows/` | CI |
| `reports/` | Generated run reports |
| `docs/` | Demo script |

---

<details>
<summary>About this repository</summary>

This is a 180-day Analytics Engineer study roadmap. The `lesson*.py` files are
daily exercises; the pipeline above is the production artifact they build up
to. Progress is tracked outside the repo.

</details>
"""


def step5_readme():
    banner("STEP 5", "README с архитектурной диаграммой")
    content = README.format(user=GITHUB_USER, repo=GITHUB_REPO)
    path = PROJECT_ROOT / "README.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(content, encoding="utf-8")
    print(f"  {len(old)} -> {len(content)} baytov")
    print("  Mermaid, а не draw.io: GitHub рендерит его прямо в README,")
    print("  диаграмма живёт в репозитории текстом и видна в diff.")
    print(f"  OK: {path.relative_to(PROJECT_ROOT)}")


# --------------------------------------------------------------------------
# STEP 6 — сценарий демо
# --------------------------------------------------------------------------
DEMO_SCRIPT = """# 2-Minute Pipeline Demo - Script

Recording notes: 1920x1080, no audio edit needed if you follow the beats.
Keep the terminal font large. Rehearse once, record once.

Prepare before recording:

```bash
python lesson81_85.py            # data loaded, pipeline green
cd production_pipeline && dagster dev -f definitions.py
```

Open three tabs in advance: Dagster UI (:3000), dbt docs (:8080), the GitHub PR.

---

## 0:00 - 0:15 | What this is

> "This is an end-to-end analytics pipeline. GitHub event data is ingested
> into a raw layer, transformed with dbt into two marts, and orchestrated by
> Dagster. Everything runs from a clean checkout with one command."

Show: README architecture diagram.

## 0:15 - 0:45 | The asset graph

Show: Dagster UI, Assets tab, the lineage graph.

> "Dagster models this as assets, not tasks. The ingest asset is partitioned
> by day. Downstream are the dbt models - the two graphs are stitched into one,
> so Dagster knows the dbt source and the ingest asset are the same object."

Click one partition, show the materialization metadata: rows synced, extracted_at.

## 0:45 - 1:15 | Quality

Show: asset checks on the raw asset, then the dbt test list.

> "Quality runs at three levels. dbt core tests answer whether a row is valid.
> dbt-expectations checks ranges and formats. Elementary compares today against
> the trailing window and flags anomalies. Asset checks gate the whole
> pipeline - if raw is empty or stale, downstream does not run."

Optional, if the recording is going well: run the negative test live.

```bash
python lesson86_88.py            # step 9 breaks data, proves tests go red
```

## 1:15 - 1:40 | Documentation

Show: dbt docs at :8080 - lineage graph, then a model page with column
descriptions and tests attached.

> "Every column is documented and every model has its tests visible in the
> catalog. This is generated from the same YAML that defines the tests, so
> documentation cannot drift from behaviour."

## 1:40 - 2:00 | CI

Show: the GitHub PR with two green checks.

> "Every pull request runs the suite on a clean database. The warehouse file
> is gitignored, so CI rebuilds the raw layer using the exact same ingestion
> function the orchestrator calls. Green here means the pipeline actually
> reproduces - not that it works on my laptop."

End on the green checkmarks.

---

## If you have 30 more seconds

Mention the Snowflake path: the same dbt project runs against Snowflake by
switching a target; the only DuckDB-specific code is one macro shim and the
JSON extraction syntax.
"""


def step6_demo_script():
    banner("STEP 6", "Сценарий 2-минутного демо")
    path = DOCS_DIR / "DEMO_SCRIPT.md"
    path.write_text(DEMO_SCRIPT, encoding="utf-8")
    print("  Сценарий с таймингами — чтобы не записывать пять дублей.")
    print("  Видео само по себе не артефакт: артефакт — это то, что в нём")
    print("  показано за две минуты без запинок.")
    print(f"  OK: {path.relative_to(PROJECT_ROOT)}")


# --------------------------------------------------------------------------
# STEP 7 — отчёт
# --------------------------------------------------------------------------
def step7_report(build_summary: str, cov_after: dict, catalog_rows: list):
    banner("STEP 7", "Отчёт")

    cols_documented = sum(c["columns_with_desc"] for c in cov_after.values())
    cols_total = sum(c["columns_documented"] for c in cov_after.values())

    md = REPORTS_DIR / "day89_90_summary.md"
    lines = [
        "# Days 89-90 - Documentation + GitHub",
        "",
        f"Сгенерировано: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Покрытие документацией",
        "",
        "| Модель | Колонок в yml | С описанием |",
        "|---|---|---|",
    ]
    for name in PROD_MODELS:
        info = cov_after.get(name, {})
        lines.append(
            f"| `{name}` | {info.get('columns_documented', 0)} "
            f"| {info.get('columns_with_desc', 0)} |"
        )
    lines += [
        "",
        f"Итого колонок с описанием: **{cols_documented} из {cols_total}**",
        "",
        "## Артефакты",
        "",
        f"- `dbt build`: `{build_summary}`",
        f"- Dagster catalog: {len(catalog_rows)} zapisey",
        "- `README.md` — Mermaid-диаграмма, quick start, CI, Snowflake",
        "- `docs/DEMO_SCRIPT.md` — сценарий видео с таймингами",
        "- `dbt_analytics/target/index.html` - dbt docs",
        "",
        "## Что осталось",
        "",
        "- Записать видео по сценарию",
        "- Docker: образ не собирался, Docker не установлен",
    ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  колонок с описанием: {cols_documented} из {cols_total}")
    print(f"  OK: {md.relative_to(PROJECT_ROOT)}")


# --------------------------------------------------------------------------
def main():
    print(SEP)
    print("  lesson89_90.py — Days 89-90: Документация + GitHub")
    print(f"  {datetime.now().isoformat(timespec='seconds')}")
    print(SEP)

    ensure_venv()
    print(f"  python: {sys.executable}")
    print(f"  dbt:    {dbt_cmd()[0]}")

    cov_before = step1_audit()
    step2_descriptions()
    build_summary, cov_after = step3_dbt_docs(cov_before)
    catalog_rows = step4_dagster_catalog()
    step5_readme()
    step6_demo_script()
    step7_report(build_summary, cov_after, catalog_rows)

    print("\n" + SEP)
    print("  ALL DONE")
    print(SEP)
    print("""
Next steps:
  1. Посмотреть документацию:
         cd dbt_analytics
         dbt docs serve --port 8080
     Lineage graph — кнопка в правом нижнем углу.

  2. Записать видео по docs/DEMO_SCRIPT.md (2 минуты, тайминги внутри).

  3. Проверить, как README выглядит на GitHub — Mermaid рендерится
     только на стороне GitHub, локальный просмотр в VS Code требует
     расширения.

Git:
  git add README.md docs/ lesson89_90.py \\
          dbt_analytics/models/schema_production.yml \\
          reports/day89_90_summary.md reports/day89_90_dagster_catalog.csv
  git commit -m "docs: Days 89-90 model docs, README, Dagster catalog"
""")


if __name__ == "__main__":
    main()
