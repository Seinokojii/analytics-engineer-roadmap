#!/usr/bin/env python3
"""
lesson86_88.py - Days 86-88: Testing + Monitoring

Запуск:
    python lesson86_88.py

Продолжает pipeline дней 81-85 (production_pipeline + dbt_analytics).
Ничего не удаляет: перед правкой каждого файла делается .bak.

Что делает:
  1. Backup dbt_project.yml / packages.yml / schema_production.yml
  2. dbt-expectations: расширенные тесты на production-моделях
  3. Elementary 0.25.1: установка + duckdb-shim для adapter.dispatch
  4. dbt deps + build elementary-моделей (служебная схема)
  5. Elementary anomaly monitors na mart_daily_events / stg_gh_events
  6. dbt build + dbt source freshness -> реальный прогон всех тестов
  7. Отчёт из таблиц elementary -> reports/
  8. GitHub Actions CI + Dockerfile + docker-compose

Важно про warehouse:
  Всё ниже работает на DuckDB и переезжает на Snowflake сменой target
  в profiles.yml. Snowflake-блок в CI заготовлен и закомментирован.
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Пути. Всё относительно этого файла — никаких абсолютных путей.
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT = PROJECT_ROOT / "dbt_analytics"
PIPELINE_DIR = PROJECT_ROOT / "production_pipeline"
REPORTS_DIR = PROJECT_ROOT / "reports"
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
CI_PROFILES_DIR = PROJECT_ROOT / ".github" / "ci_profiles"

REPORTS_DIR.mkdir(exist_ok=True)

DBT_PROJECT_YML = DBT_PROJECT / "dbt_project.yml"
PACKAGES_YML = DBT_PROJECT / "packages.yml"
SCHEMA_YML = DBT_PROJECT / "models" / "schema_production.yml"
SHIM_MACRO = DBT_PROJECT / "macros" / "duckdb_elementary_shims.sql"

ELEMENTARY_VERSION = "0.25.1"
ELEMENTARY_SCHEMA = "main_elementary"

SEP = "=" * 62


def venv_python() -> Path:
    """Интерпретатор проектного .venv."""
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return PROJECT_ROOT / ".venv" / rel


def ensure_venv() -> None:
    """Перезапускает скрипт в .venv, если запущен другим Python.

    Зачем: dbt_cmd() берёт dbt рядом с sys.executable. Если скрипт
    запущен глобальным Python (например 3.14 из Microsoft Store), он
    возьмёт тамошний dbt — а он не обязан быть рабочим. Реальный случай:
        mashumaro.exceptions.UnserializableField: Field "schema" ...
    Это не ошибка dbt-проекта, это не то окружение.
    """
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
    # Без flush эти две строки при редиректе в файл уедут в конец лога:
    # stdout родителя буферизируется блоками и сбрасывается на выходе,
    # а дочерний процесс пишет в тот же дескриптор раньше.
    sys.stdout.flush()
    env = dict(os.environ, AE_LESSON_REEXEC="1")
    proc = subprocess.run(
        [str(vpy), str(Path(__file__).resolve()), *sys.argv[1:]], env=env
    )
    sys.exit(proc.returncode)


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def dbt_cmd() -> list:
    """dbt.exe рядом с текущим интерпретатором, иначе — модуль."""
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    return [str(exe)] if exe.exists() else [sys.executable, "-m", "dbt.cli.main"]


def run_dbt(args: list, allow_fail: bool = False) -> tuple:
    """Запускает dbt в dbt_analytics. Возвращает (returncode, stdout)."""
    cmd = dbt_cmd() + args
    print(f"  $ dbt {' '.join(args)}")
    proc = subprocess.run(
        cmd,
        cwd=str(DBT_PROJECT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not allow_fail:
        tail = "\n".join(out.strip().splitlines()[-25:])
        print(tail)
        raise RuntimeError(f"dbt {' '.join(args)} failed (rc={proc.returncode})")
    return proc.returncode, out


def dbt_summary(out: str) -> str:
    """Выдёргивает строку 'Done. PASS=.. WARN=.. ERROR=..' из лога."""
    for line in reversed(out.splitlines()):
        if "Done." in line and "PASS=" in line:
            return line.split("Done.")[-1].strip()
    return "no summary line"


def backup_once(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)
        print(f"  backup: {bak.relative_to(PROJECT_ROOT)}")
    elif bak.exists():
        print(f"  backup exists: {bak.relative_to(PROJECT_ROOT)}")


# --------------------------------------------------------------------------
# STEP 1
# --------------------------------------------------------------------------
def step1_backup():
    banner("STEP 1", "Бэкап редактируемых файлов")
    for p in (DBT_PROJECT_YML, PACKAGES_YML, SCHEMA_YML):
        backup_once(p)
    print("  OK: откат возможен копированием .bak обратно")


# --------------------------------------------------------------------------
# STEP 2 - dbt-expectations
# --------------------------------------------------------------------------
SCHEMA_WITH_EXPECTATIONS = """version: 2

# Day 86-88: Testing + Monitoring
# Три уровня проверок на одних и тех же моделях:
#   1. dbt core tests   - unique / not_null / accepted_values / relationships
#   2. dbt-expectations — диапазоны, форматы, сравнение колонок
#   3. elementary       — аномалии во времени (добавляются в STEP 5)

models:
  - name: stg_gh_events
    description: "Нормализованные GitHub Events из Airbyte raw"
    tests:
      # Пустая таблица — это зелёный dbt run и сломанный dashboard.
      # Ровно тот случай, который not_null не ловит.
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
    columns:
      - name: event_id
        description: "Уникальный ID события в GitHub"
        tests: [unique, not_null]
      - name: event_type
        tests:
          - not_null
          - accepted_values:
              values: ['PushEvent', 'PullRequestEvent', 'IssuesEvent',
                       'WatchEvent', 'ForkEvent']
      - name: actor_login
        tests:
          - not_null
          # stg_gh_events делает LOWER(actor_login).
          # Тест фиксирует это как контракт, а не как случайность.
          - dbt_expectations.expect_column_values_to_match_regex:
              regex: "^[^A-Z]*$"
      - name: repo_name
        tests: [not_null]
      - name: payload_size
        tests:
          - not_null
          # В staging уже есть WHERE payload_size > 0.
          # Верхняя граница ловит мусор от источника.
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 1
              max_value: 100000
      - name: event_date
        tests: [not_null]

  - name: mart_daily_events
    description: "Инкрементальный mart: активность по дням"
    tests:
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
      # Активных авторов не может быть больше, чем событий.
      # Классический симптом сломанного JOIN — fan-out.
      - dbt_expectations.expect_column_pair_values_A_to_be_greater_than_B:
          column_A: events
          column_B: active_actors
          or_equal: true
    columns:
      - name: event_date
        tests: [unique, not_null]
      - name: events
        tests:
          - not_null
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 1
      - name: active_actors
        tests: [not_null]
      - name: active_repos
        tests: [not_null]

  - name: mart_repo_activity
    description: "Активность по репозиториям"
    tests:
      - dbt_expectations.expect_table_row_count_to_be_between:
          min_value: 1
      - dbt_expectations.expect_column_pair_values_A_to_be_greater_than_B:
          column_A: events
          column_B: contributors
          or_equal: true
    columns:
      - name: repo_name
        tests: [unique, not_null]
      - name: contributors
        tests:
          - not_null
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 1
      - name: events_per_day
        tests:
          - dbt_expectations.expect_column_values_to_be_between:
              min_value: 0
"""


def step2_dbt_expectations():
    banner("STEP 2", "dbt-expectations: тесты за пределами not_null")
    SCHEMA_YML.write_text(SCHEMA_WITH_EXPECTATIONS, encoding="utf-8")
    n = SCHEMA_WITH_EXPECTATIONS.count("dbt_expectations.")
    print(f"  записан {SCHEMA_YML.relative_to(PROJECT_ROOT)}")
    print(f"  добавлено dbt-expectations тестов: {n}")
    print("  пакет уже был в packages.yml с Day 046-050 — ставить не нужно")


# --------------------------------------------------------------------------
# STEP 3 - Elementary + duckdb shim
# --------------------------------------------------------------------------
SHIM_SQL = """{#
    macros/duckdb_elementary_shims.sql
    Day 86-88.

    Elementary диспатчит edr_multi_value_in и имеет реализации для
    default / bigquery / redshift / fabric / sqlserver. duckdb__ net,
    поэтому он падает в default__, который генерирует tuple IN:

        (a, b) in (select x, y from t)

    DuckDB так не умеет:
        Binder Error: Subquery returns 2 columns - expected 1

    Чиним тем же приёмом, что Elementary применил для T-SQL —
    коррелированный EXISTS. Он не требует CONCAT и не ломается на NULL,
    v otlichie ot bigquery/redshift varianta.

    Чтобы dbt взял этот макрос вместо пакетного, в dbt_project.yml
    propisan dispatch: search_order ['analytics_project', 'elementary'].
#}

{%- macro duckdb__edr_multi_value_in(source_cols, target_cols, target_table) -%}
    exists (
        select 1
        from {{ target_table }} as __edr_mvi
        where
            {%- for i in range(source_cols | length) %}
                __edr_mvi.{{ target_cols[i] }} = {{ source_cols[i] }}
                {%- if not loop.last %} and {% endif %}
            {%- endfor %}
    )
{%- endmacro -%}
"""

DISPATCH_BLOCK = """
# Day 86-88: Elementary не имеет duckdb__ реализаций части макросов.
# search_order заставляет dbt сначала искать макрос в нашем проекте,
# и только потом в пакете. См. macros/duckdb_elementary_shims.sql
dispatch:
  - macro_namespace: elementary
    search_order: ['analytics_project', 'elementary']
"""

ELEMENTARY_MODELS_BLOCK = """
  # Day 86-88: служебные модели Elementary в отдельной схеме
  elementary:
    +schema: elementary
"""


def step3_elementary_setup():
    banner("STEP 3", f"Elementary {ELEMENTARY_VERSION} + duckdb shim")

    # 3.1 packages.yml
    pkg = PACKAGES_YML.read_text(encoding="utf-8")
    if "elementary-data/elementary" in pkg:
        print("  packages.yml: elementary уже есть")
    else:
        pkg = pkg.rstrip() + (
            f"\n  - package: elementary-data/elementary"
            f"\n    version: {ELEMENTARY_VERSION}\n"
        )
        PACKAGES_YML.write_text(pkg, encoding="utf-8")
        print(f"  packages.yml: добавлен elementary {ELEMENTARY_VERSION}")

    # 3.2 dbt_project.yml — dispatch + схема для elementary моделей
    proj = DBT_PROJECT_YML.read_text(encoding="utf-8")
    changed = False
    if "macro_namespace: elementary" not in proj:
        proj = proj.replace("\nmodels:\n", DISPATCH_BLOCK + "\nmodels:\n", 1)
        changed = True
        print("  dbt_project.yml: добавлен dispatch для elementary")
    if re.search(r"^\s+elementary:\s*$", proj, flags=re.M) is None:
        proj = proj.rstrip() + "\n" + ELEMENTARY_MODELS_BLOCK
        changed = True
        print("  dbt_project.yml: elementary -> +schema: elementary")
    if changed:
        DBT_PROJECT_YML.write_text(proj, encoding="utf-8")
    else:
        print("  dbt_project.yml: уже настроен")

    # 3.3 shim-макрос
    SHIM_MACRO.write_text(SHIM_SQL, encoding="utf-8")
    print(f"  zapisan {SHIM_MACRO.relative_to(PROJECT_ROOT)}")

    # 3.4 установка пакетов
    _, out = run_dbt(["deps"])
    for line in out.splitlines():
        if "Installed from version" in line or "Installing" in line:
            print("   ", line.split("  ", 1)[-1].strip())
    print("  OK: пакеты установлены")


# --------------------------------------------------------------------------
# STEP 4 — служебные модели Elementary
# --------------------------------------------------------------------------
def step4_elementary_models():
    banner("STEP 4", "Build служебных моделей Elementary")
    print("  Elementary хранит историю прогонов в своих таблицах.")
    print("  Без них anomaly detection не с чем сравнивать.")
    _, out = run_dbt(["run", "--select", "elementary"])
    print(f"  {dbt_summary(out)}")
    print(f"  OK: служебная схема {ELEMENTARY_SCHEMA}")


# --------------------------------------------------------------------------
# STEP 5 - anomaly monitors
# --------------------------------------------------------------------------
def step5_anomaly_monitors():
    banner("STEP 5", "Elementary: anomaly monitors")
    text = SCHEMA_YML.read_text(encoding="utf-8")
    if "elementary.volume_anomalies" in text:
        print("  мониторы уже прописаны")
        return
    # Мониторы дописываются в существующие описания моделей.
    # Отдельным файлом нельзя: dbt запрещает описывать одну и ту же
    # модель дважды — "duplicate patch for model".
    text = _merge_monitors(text)
    SCHEMA_YML.write_text(text, encoding="utf-8")
    print(f"  monitory vpisany v {SCHEMA_YML.relative_to(PROJECT_ROOT)}")


def _merge_monitors(text: str) -> str:
    """Вставляет elementary-тесты в уже существующие описания моделей.

    dbt запрещает описывать одну модель в двух местах ("duplicate patch"),
    поэтому мониторы добавляются в тот же блок, а не отдельным файлом.
    """
    # mart_daily_events: config + volume_anomalies
    text = text.replace(
        '  - name: mart_daily_events\n'
        '    description: "Инкрементальный mart: активность по дням"\n'
        '    tests:\n',
        '  - name: mart_daily_events\n'
        '    description: "Инкрементальный mart: активность по дням"\n'
        '    config:\n'
        '      elementary:\n'
        '        timestamp_column: "event_date"\n'
        '    tests:\n'
        '      # Резкое падение числа строк в дне — сломанный ingest.\n'
        '      - elementary.volume_anomalies:\n'
        '          time_bucket:\n'
        '            period: day\n'
        '            count: 1\n',
        1,
    )
    # stg_gh_events: config + volume_anomalies
    text = text.replace(
        '  - name: stg_gh_events\n'
        '    description: "Нормализованные GitHub Events из Airbyte raw"\n'
        '    tests:\n',
        '  - name: stg_gh_events\n'
        '    description: "Нормализованные GitHub Events из Airbyte raw"\n'
        '    config:\n'
        '      elementary:\n'
        '        timestamp_column: "created_at"\n'
        '    tests:\n'
        '      - elementary.volume_anomalies:\n'
        '          time_bucket:\n'
        '            period: day\n'
        '            count: 1\n',
        1,
    )
    # kolonochnye anomalii
    text = text.replace(
        '      - name: events\n'
        '        tests:\n'
        '          - not_null\n',
        '      - name: events\n'
        '        tests:\n'
        '          - not_null\n'
        '          - elementary.column_anomalies:\n'
        '              column_anomalies: [null_count, average, max]\n',
        1,
    )
    text = text.replace(
        '      - name: payload_size\n'
        '        tests:\n'
        '          - not_null\n',
        '      - name: payload_size\n'
        '        tests:\n'
        '          - not_null\n'
        '          - elementary.column_anomalies:\n'
        '              column_anomalies: [null_count, average]\n',
        1,
    )
    return text


# --------------------------------------------------------------------------
# STEP 6 — реальный прогон
# --------------------------------------------------------------------------
def step6_run_tests():
    banner("STEP 6", "dbt build + source freshness")

    print("\n  6.1 source freshness (raw из Airbyte)")
    rc, out = run_dbt(["source", "freshness"], allow_fail=True)
    for line in out.splitlines():
        if any(k in line for k in ("PASS freshness", "WARN freshness",
                                   "ERROR STALE", "Done.")):
            print("   ", line.strip())
    print(f"    rc={rc} (WARN/ERROR здесь — нормально, данные за 04-06.08)")

    print("\n  6.2 dbt build tag:production_pipeline")
    rc, out = run_dbt(
        ["build", "--select", "tag:production_pipeline"], allow_fail=True
    )
    summary = dbt_summary(out)
    print(f"    {summary}")

    failures = [
        ln.strip() for ln in out.splitlines()
        if ln.strip().startswith(("Failure in test", "Runtime Error"))
    ]
    if failures:
        print("\n  Nezelyonye testy:")
        for f in failures[:10]:
            print(f"    - {f}")
    return summary, rc


# --------------------------------------------------------------------------
# STEP 7 — отчёт из таблиц Elementary
# --------------------------------------------------------------------------
def step7_report(build_summary: str):
    banner("STEP 7", "Отчёт из таблиц Elementary")

    import duckdb

    db = DBT_PROJECT / "analytics.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = [
            r[0] for r in con.execute(
                "select table_name from information_schema.tables "
                "where table_schema = ? order by 1",
                [ELEMENTARY_SCHEMA],
            ).fetchall()
        ]
        print(f"  таблиц Elementary: {len(tables)}")

        target = None
        for cand in ("elementary_test_results", "dbt_tests", "test_results"):
            if cand in tables:
                target = cand
                break

        if target is None:
            print("  elementary_test_results пока нет — нужен хотя бы один")
            print("  прогон 'dbt test' после установки пакета")
            csv_path = None
        else:
            df = con.execute(
                f"""
                SELECT
                    test_short_name          AS test_name,
                    table_name,
                    column_name,
                    status,
                    severity,
                    detected_at
                FROM {ELEMENTARY_SCHEMA}.{target}
                ORDER BY detected_at DESC, test_name
                """
            ).fetchdf()
            csv_path = REPORTS_DIR / "day86_88_elementary_tests.csv"
            df.to_csv(csv_path, index=False)
            print(f"  строк в {target}: {len(df)}")
            if len(df):
                counts = df["status"].value_counts().to_dict()
                print(f"  по статусам: {counts}")
            print(f"  OK: {csv_path.relative_to(PROJECT_ROOT)}")
    finally:
        con.close()

    md = REPORTS_DIR / "day86_88_summary.md"
    md.write_text(
        "# Days 86-88 - Testing + Monitoring\n\n"
        f"Sgenerirovano: {datetime.now().isoformat(timespec='seconds')}\n\n"
        f"- dbt build (tag:production_pipeline): `{build_summary}`\n"
        f"- Elementary: {ELEMENTARY_VERSION}, shema `{ELEMENTARY_SCHEMA}`\n"
        f"- Таблиц Elementary: {len(tables)}\n"
        "- CI: `.github/workflows/dbt_ci.yml`\n"
        "- Docker: `Dockerfile`, `docker-compose.yml`\n\n"
        "## Perehod na Snowflake\n\n"
        "1. profiles.yml: target `prod` type snowflake\n"
        "2. GitHub Secrets: SNOWFLAKE_ACCOUNT / USER / PASSWORD / ROLE /\n"
        "   WAREHOUSE / DATABASE\n"
        "3. Raskommentirovat job `dbt-snowflake` v dbt_ci.yml\n"
        "4. Удалить macros/duckdb_elementary_shims.sql — на Snowflake\n"
        "   default__ dispatch работает\n",
        encoding="utf-8",
    )
    print(f"  OK: {md.relative_to(PROJECT_ROOT)}")


# --------------------------------------------------------------------------
# STEP 8 - CI + Docker
# --------------------------------------------------------------------------
CI_PROFILES = """# .github/ci_profiles/profiles.yml
# Отдельная папка, а НЕ dbt_analytics/profiles.yml:
# dbt 1.5+ читает profiles.yml из папки проекта раньше, чем ~/.dbt,
# и локальная разработка сломалась бы.

analytics:
  target: ci
  outputs:
    ci:
      type: duckdb
      path: ci_analytics.duckdb
      schema: main

    # Snowflake — включается когда появится аккаунт.
    # Никаких паролей в файле: только env_var, которые GitHub
    # подставляет из Secrets.
    prod:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('SNOWFLAKE_USER') }}"
      password: "{{ env_var('SNOWFLAKE_PASSWORD') }}"
      role: "{{ env_var('SNOWFLAKE_ROLE', 'TRANSFORMER') }}"
      warehouse: "{{ env_var('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH') }}"
      database: "{{ env_var('SNOWFLAKE_DATABASE', 'ANALYTICS') }}"
      schema: "dbt_ci"
      threads: 4
"""

CI_WORKFLOW = """name: dbt CI (Days 86-88)

# Запускается на каждый PR. Задача: PR не должен мержиться,
# если модели не компилируются или тесты не зелёные.

on:
  pull_request:
    branches: [main, dev]
    paths:
      - 'dbt_analytics/**'
      - 'production_pipeline/**'
      - '.github/workflows/**'
  workflow_dispatch:

env:
  DBT_PROFILES_DIR: ${{ github.workspace }}/.github/ci_profiles

jobs:
  # -----------------------------------------------------------------
  # Job 1 — дешёвый: ловит сломанный Jinja и опечатки в ref()
  # без единого запроса к данным.
  # -----------------------------------------------------------------
  parse:
    name: dbt parse + compile
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: Install dbt
        run: pip install "dbt-core~=1.11.0" "dbt-duckdb~=1.8.0" --quiet
      - name: dbt deps
        working-directory: dbt_analytics
        run: dbt deps
      - name: dbt parse
        working-directory: dbt_analytics
        run: dbt parse --target ci
      - name: dbt compile
        working-directory: dbt_analytics
        run: dbt compile --target ci --select tag:production_pipeline

  # -----------------------------------------------------------------
  # Job 2 — настоящий build на чистой БД.
  # *.duckdb в .gitignore, поэтому raw собирается из CSV тем же
  # кодом, что и в Dagster — ingest_core.sync_partition.
  # -----------------------------------------------------------------
  build-and-test:
    name: dbt build + test (DuckDB)
    runs-on: ubuntu-latest
    needs: parse
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: Install deps
        run: |
          pip install "dbt-core~=1.11.0" "dbt-duckdb~=1.8.0" --quiet
          pip install duckdb pandas --quiet
      - name: Seed raw from CSV
        run: python .github/scripts/ci_seed_raw.py
      - name: dbt deps
        working-directory: dbt_analytics
        run: dbt deps
      # Elementary хранит историю прогонов в своих таблицах, и её
      # anomaly-тесты читают их. На чистой БД этих таблиц нет,
      # и build падает:
      #   Catalog Error: Schema with name main_elementary does not exist
      # Поэтому сначала строим служебные модели — тот же порядок,
      # что и в lesson86_88.py (STEP 4 до STEP 6).
      - name: Build Elementary models
        working-directory: dbt_analytics
        run: dbt run --target ci --select elementary
      - name: dbt build
        working-directory: dbt_analytics
        run: dbt build --target ci --select tag:production_pipeline
      - name: dbt source freshness
        working-directory: dbt_analytics
        continue-on-error: true
        run: dbt source freshness --target ci
      - name: Upload dbt artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: dbt-target
          path: |
            dbt_analytics/target/
            dbt_analytics/logs/
          retention-days: 7

  # -----------------------------------------------------------------
  # Job 3 — Snowflake. Включить, когда будет аккаунт и Secrets.
  # -----------------------------------------------------------------
  # dbt-snowflake:
  #   name: dbt build + test (Snowflake)
  #   runs-on: ubuntu-latest
  #   needs: parse
  #   env:
  #     SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
  #     SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
  #     SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
  #     SNOWFLAKE_ROLE:      ${{ secrets.SNOWFLAKE_ROLE }}
  #     SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
  #     SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
  #   steps:
  #     - uses: actions/checkout@v4
  #     - uses: actions/setup-python@v5
  #       with:
  #         python-version: '3.12'
  #     - run: pip install "dbt-core~=1.11.0" "dbt-snowflake~=1.11.0" --quiet
  #     - working-directory: dbt_analytics
  #       run: dbt deps
  #     - working-directory: dbt_analytics
  #       run: dbt build --target prod --select tag:production_pipeline
"""

CI_SEED_SCRIPT = '''#!/usr/bin/env python3
"""
.github/scripts/ci_seed_raw.py
Day 86-88: наполняет raw таблицу в CI.

*.duckdb в .gitignore, поэтому в CI БД пустая. Используем тот же
ingest_core.sync_partition, что и Dagster asset — одна логика
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
'''

DOCKERFILE = """# Dockerfile - Days 86-88
# Воспроизводимость: одна команда и у любого человека тот же стек.
# Multi-stage: builder ставит зависимости, runtime остаётся тонким.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \\
 && /opt/venv/bin/pip install --upgrade pip \\
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

# git нужен dbt deps: пакеты тянутся из GitHub
RUN apt-get update \\
 && apt-get install -y --no-install-recommends git \\
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \\
    PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    DAGSTER_HOME=/app/dagster_home \\
    DBT_PROFILES_DIR=/app/.github/ci_profiles

WORKDIR /app

# Сначала манифесты зависимостей — слой кешируется и не
# пересобирается при правке моделей.
COPY dbt_analytics/packages.yml dbt_analytics/dbt_project.yml ./dbt_analytics/
RUN cd dbt_analytics && dbt deps || true

COPY . .

RUN useradd --create-home --uid 1000 analytics \\
 && mkdir -p /app/dagster_home \\
 && chown -R analytics:analytics /app
USER analytics

EXPOSE 3000

CMD ["dagster", "dev", "-m", "definitions", "-h", "0.0.0.0", "-p", "3000"]
"""

DOCKER_COMPOSE = """# docker-compose.yml - Days 86-88
# docker compose up -> весь стек поднимается одной командой.

services:
  # Dagster UI + оркестрация (Days 61-85)
  dagster:
    build: .
    image: ae-pipeline:latest
    container_name: ae_dagster
    working_dir: /app/production_pipeline
    environment:
      DAGSTER_HOME: /app/dagster_home
      DBT_PROFILES_DIR: /app/.github/ci_profiles
    ports:
      - "3000:3000"
    volumes:
      - ./dbt_analytics:/app/dbt_analytics
      - ./production_pipeline:/app/production_pipeline
      - dagster_state:/app/dagster_home
    restart: unless-stopped

  # dbt docs — поднимается на Days 89-90
  dbt-docs:
    build: .
    image: ae-pipeline:latest
    container_name: ae_dbt_docs
    working_dir: /app/dbt_analytics
    environment:
      DBT_PROFILES_DIR: /app/.github/ci_profiles
    command: >
      sh -c "dbt deps &&
             dbt docs generate --target ci &&
             dbt docs serve --port 8080 --host 0.0.0.0 --no-browser"
    ports:
      - "8080:8080"
    volumes:
      - ./dbt_analytics:/app/dbt_analytics
    profiles: ["docs"]

volumes:
  dagster_state:
"""

DOCKERIGNORE = """.venv/
venv312/
__pycache__/
*.pyc
*.duckdb
.git/
.pytest_cache/
dagster_home/
dbt_analytics/target/
dbt_analytics/dbt_packages/
dbt_analytics/logs/
production_pipeline/compute_logs/
reports/
notes/
*.bak
"""


def step8_ci_and_docker():
    banner("STEP 8", "GitHub Actions CI + Docker")

    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    CI_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    scripts_dir = PROJECT_ROOT / ".github" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    files = {
        CI_PROFILES_DIR / "profiles.yml": CI_PROFILES,
        WORKFLOWS_DIR / "dbt_ci.yml": CI_WORKFLOW,
        scripts_dir / "ci_seed_raw.py": CI_SEED_SCRIPT,
        PROJECT_ROOT / "Dockerfile": DOCKERFILE,
        PROJECT_ROOT / "docker-compose.yml": DOCKER_COMPOSE,
        PROJECT_ROOT / ".dockerignore": DOCKERIGNORE,
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
        print(f"  zapisan {path.relative_to(PROJECT_ROOT)}")

    # Проверка YAML-синтаксиса workflow — дешевле, чем узнать об ошибке
    # после push.
    try:
        import yaml

        for f in (WORKFLOWS_DIR / "dbt_ci.yml", PROJECT_ROOT / "docker-compose.yml",
                  CI_PROFILES_DIR / "profiles.yml"):
            yaml.safe_load(f.read_text(encoding="utf-8"))
            print(f"  YAML OK: {f.name}")
    except ImportError:
        print("  pyyaml не установлен — YAML не проверен")

    if shutil.which("docker") is None:
        print("\n  ! Docker не установлен на этой машине.")
        print("    Файлы написаны, но 'docker compose up' здесь не проверен.")
        print("    Это честная незакрытая часть блока.")


# --------------------------------------------------------------------------
# STEP 9 — негативный тест: доказать, что тесты вообще краснеют
# --------------------------------------------------------------------------
BAD_ROWS = [
    # payload_size vyshe verhney granitsy (max_value: 100000)
    ("payload_size", 999999, "PushEvent"),
    # event_type vne accepted_values
    ("event_type", 500, "MysteryEvent"),
]


def step9_negative_test():
    banner("STEP 9", "Негативный тест: ломаем данные намеренно")
    print("  Набор тестов, который никогда не краснел — не проверен.")
    print("  Здесь портим raw, ждём ERROR, потом восстанавливаем.")

    import json as _json
    import uuid

    import duckdb

    db = DBT_PROJECT / "analytics.duckdb"
    backup = DBT_PROJECT / "analytics.duckdb.pretest_bak"

    shutil.copy2(db, backup)
    print(f"\n  9.1 kopiya BD: {backup.name}")

    con = duckdb.connect(str(db))
    try:
        for _, size, etype in BAD_ROWS:
            payload = {
                "event_id": f"bad-{uuid.uuid4()}",
                "event_type": etype,
                "actor": "chaos_monkey",
                "repo": "acme/broken",
                "created_at": "2026-08-06 12:00:00",
                "payload_size": size,
            }
            con.execute(
                "INSERT INTO raw.airbyte_raw_gh_events VALUES "
                "(?, ?, ?, CAST(? AS DATE))",
                [
                    str(uuid.uuid4()),
                    _json.dumps(payload),
                    datetime.now(),
                    "2026-08-06",
                ],
            )
        print(f"  9.2 вставлено битых строк: {len(BAD_ROWS)}")
    finally:
        con.close()

    print("\n  9.3 прогон тестов на испорченных данных")
    rc, out = run_dbt(
        ["build", "--select", "tag:production_pipeline"], allow_fail=True
    )
    print(f"    {dbt_summary(out)}")

    red = sorted(
        {
            ln.split("Failure in test ")[1].split(" ")[0]
            for ln in out.splitlines()
            if "Failure in test " in ln
        }
    )
    if red:
        print("    Pokrasneli:")
        for t in red:
            print(f"      - {t}")
    else:
        print("    ! Ничего не покраснело — тесты не ловят этот класс ошибок")

    print("\n  9.4 восстановление БД из копии")
    shutil.move(str(backup), str(db))
    rc2, out2 = run_dbt(
        ["build", "--select", "tag:production_pipeline"], allow_fail=True
    )
    print(f"    после восстановления: {dbt_summary(out2)}")

    ok = bool(red) and rc != 0 and rc2 == 0
    print(f"\n  {'OK' if ok else 'ВНИМАНИЕ'}: alerting {'проверен' if ok else 'не подтверждён'}")
    return red


# --------------------------------------------------------------------------
def main():
    print(SEP)
    print("  lesson86_88.py - Days 86-88: Testing + Monitoring")
    print(f"  {datetime.now().isoformat(timespec='seconds')}")
    print(SEP)

    ensure_venv()

    # Явно показываем, чем работаем: почти все "непонятные" ошибки
    # dbt на этом проекте — это не тот Python.
    print(f"  python: {sys.executable}")
    print(f"  dbt:    {dbt_cmd()[0]}")

    step1_backup()
    step2_dbt_expectations()
    step3_elementary_setup()
    step4_elementary_models()
    step5_anomaly_monitors()
    build_summary, _ = step6_run_tests()
    step7_report(build_summary)
    step8_ci_and_docker()
    step9_negative_test()

    print("\n" + SEP)
    print("  ALL DONE")
    print(SEP)
    print("""
Next steps:
  1. Посмотреть отчёт:
     reports/day86_88_summary.md
     reports/day86_88_elementary_tests.csv

  2. STEP 9 уже сломал данные и восстановил их автоматически.
     Ручной вариант того же — через Dagster UI, чтобы увидеть
     красный asset check и запись в production_pipeline/alerts.log:
         cd production_pipeline && dagster dev

  3. Docker (когда будет установлен):
         docker compose build
         docker compose up

  4. CI проверяется только на реальном PR:
         git checkout -b day86-88-testing
         git push origin day86-88-testing
         gh pr create   (ili knopka na GitHub)

Git:
  git add dbt_analytics/models/schema_production.yml \\
          dbt_analytics/dbt_project.yml \\
          dbt_analytics/packages.yml \\
          dbt_analytics/macros/duckdb_elementary_shims.sql \\
          .github/ Dockerfile docker-compose.yml .dockerignore \\
          lesson86_88.py
  git commit -m "feat: Days 86-88 dbt-expectations, Elementary, CI, Docker"
  git push origin main
""")


if __name__ == "__main__":
    main()
