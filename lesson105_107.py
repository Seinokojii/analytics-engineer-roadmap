#!/usr/bin/env python3
"""
lesson105_107.py — Days 105-107: dbt Advanced Patterns — dbt Mesh

Запуск:
    python lesson105_107.py

Нужен dbt-loom в том же venv:
    uv pip install --python ~/.venvs/ae/bin/python dbt-loom

Кусок монолита dbt_analytics разрезан на два проекта в dbt_mesh/:
  platform/  upstream. Silver (access: private) + Gold с контрактом:
             fct_orders и fct_subscriptions — public, dim_subscribers —
             protected. fct_subscriptions версионирована: v1 и v2
  finance/   downstream. Пять витрин и exposures. Своих сырых данных
             нет, всё через ref('platform', 'модель')

Cross-project ref в dbt Core сам не работает: это фича dbt platform
Enterprise (metadata service). Здесь её закрывает плагин dbt-loom —
читает manifest.json платформы и вставляет её публичные модели
в граф finance как внешние узлы.

Что урок проверяет:
  1. Карта разреза по manifest монолита: какие рёбра рвёт граница,
     где downstream читал чужую внутреннюю модель
  2. Сборка platform: уровни доступа, контракты, версии
  3. Сборка finance через dbt-loom: строит только своё, lineage
     до моделей platform
  4. Пакет против Mesh: тот же finance, platform подключена как package
  5. Governance: private / protected / сломанный контракт /
     breaking change с версией и без
  6. Версии модели: кто на v1, кто на v2, чем они отличаются
  7. Паритет: витрины finance против тех же витрин монолита
  8. SQL под Snowflake: Dynamic Tables + Mesh на уровне аккаунта

Что здесь хуже оригинала — честно:
  Оба проекта пишут в один файл DuckDB — в Snowflake это были бы
  разные базы или схемы с разными ролями, и грантов тут нет.
  dbt-loom читает manifest с диска; в проде это артефакт прод-деплоя
  (S3 / GCS / dbt Cloud API), и его свежесть — отдельная проблема.
  Dynamic Tables на DuckDB нет: модель mart_mrr_live выключена,
  скрипт 23 не выполнялся.

Рабочую analytics.duckdb урок не трогает: монолит для сверки
собирается в копии во временной папке, с отдельным target-path.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent
MONOLITH = PROJECT_ROOT / "dbt_analytics"
MONOLITH_DB = MONOLITH / "analytics.duckdb"
MONOLITH_MANIFEST = MONOLITH / "target" / "manifest.json"
MESH = PROJECT_ROOT / "dbt_mesh"
PLATFORM = MESH / "platform"
FINANCE = MESH / "finance"
MESH_DB = MESH / "mesh.duckdb"
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# dbt Core из того же venv, что и python: в PATH может стоять
# dbt Fusion, а он не умеет DuckDB (грабли дня 81-85).
DBT = Path(sys.executable).parent / "dbt"

SEP = "=" * 62

PLATFORM_MODELS = {
    "stg_orders", "stg_users", "stg_saas_users", "stg_subscriptions",
    "fct_orders", "fct_subscriptions", "dim_subscribers",
}
FINANCE_MODELS = [
    "mart_ltv", "mart_rfm_segments", "mart_mrr_monthly",
    "mart_cohort_retention", "monthly_revenue_pivot",
]

PROBE = FINANCE / "models" / "zz_mesh_probe.sql"


def banner(step: str, title: str) -> None:
    print("\n" + SEP)
    print(f"  {step}: {title}")
    print(SEP)


def write_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")


def write_csv(path: Path, header, rows) -> Path:
    # lineterminator обязателен: csv.writer по умолчанию пишет \r\n
    # даже на Linux. Ловилось уже дважды — в 03927efc и 03068247.
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"  OK  {path.relative_to(PROJECT_ROOT)}")
    return path


def dbt(project: Path, *args: str, db: Path = MESH_DB, profiles: Path = MESH,
        check: bool = True) -> tuple[int, str]:
    """Запуск dbt в каталоге проекта. MESH_DB_PATH читает dbt_mesh/profiles.yml."""
    env = {**os.environ, "MESH_DB_PATH": str(db)}
    proc = subprocess.run(
        [str(DBT), *args, "--profiles-dir", str(profiles)],
        cwd=project, capture_output=True, text=True, env=env,
    )
    out = proc.stdout + proc.stderr
    if check and proc.returncode != 0:
        print("\n".join(out.splitlines()[-30:]))
        raise SystemExit(f"  FAIL: dbt {' '.join(args)} в {project.name} -> exit {proc.returncode}")
    return proc.returncode, out


def dbt_summary(out: str) -> str:
    m = re.search(r"Done\. (PASS=\d+ WARN=\d+ ERROR=\d+ SKIP=\d+.*TOTAL=\d+)", out)
    return m.group(1) if m else "?"


def built_by_package(project: Path) -> Counter:
    """Что dbt реально выполнил: (тип, проект-владелец) из run_results.json."""
    rr = json.loads((project / "target" / "run_results.json").read_text(encoding="utf-8"))
    return Counter(
        (r["unique_id"].split(".")[0], r["unique_id"].split(".")[1])
        for r in rr["results"]
    )


def fetch_one(con, sql: str) -> tuple:
    """fetchone() типизирован как tuple | None — проверка делает контракт явным."""
    row = con.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"запрос не вернул строк: {sql[:60]}")
    return row


def seeds_fingerprint() -> dict[str, str]:
    """sha256 сырых CSV монолита. Урок их не пишет, но dbt пишет рядом:
    с абсолютным seed-path он однажды перезаписал их текстом SQL."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((MONOLITH / "data").glob("*.csv"))
    }


def with_probe(sql: str):
    """Временная модель-проба в finance. Удаляется всегда, даже при падении."""
    class _Probe:
        def __enter__(self):
            PROBE.write_text(sql, encoding="utf-8")
        def __exit__(self, *exc):
            PROBE.unlink(missing_ok=True)
    return _Probe()


def patched(path: Path, old: str, new: str):
    """Временная правка файла с гарантированным откатом."""
    class _Patch:
        def __enter__(self):
            self.orig = path.read_text(encoding="utf-8")
            if old not in self.orig:
                raise RuntimeError(f"{path.name}: не найден фрагмент для пробы: {old!r}")
            path.write_text(self.orig.replace(old, new, 1), encoding="utf-8")
        def __exit__(self, *exc):
            path.write_text(self.orig, encoding="utf-8")
    return _Patch()


# ═══════════════════════════════════════════════════════════
#  Шаги
# ═══════════════════════════════════════════════════════════

def step1_carve_map():
    banner("STEP 1", "Карта разреза по manifest монолита")
    m = json.loads(MONOLITH_MANIFEST.read_text(encoding="utf-8"))
    by_name = {
        n["name"]: n for n in m["nodes"].values()
        if n["resource_type"] == "model" and n["package_name"] == "analytics_project"
    }
    rows, holes = [], []
    for name in FINANCE_MODELS:
        for dep in by_name[name]["depends_on"]["nodes"]:
            dep_name = dep.split(".")[-1]
            if dep_name not in PLATFORM_MODELS:
                continue
            layer = "silver" if dep_name.startswith("stg_") else "gold"
            verdict = "ok: Gold станет public" if layer == "gold" else "ДЫРА: читает чужой Silver"
            if layer == "silver":
                holes.append((name, dep_name))
            rows.append((name, dep_name, layer, verdict))
            print(f"  {name:24} -> {dep_name:20} [{layer}]  {verdict}")

    interface = {r[1] for r in rows if r[2] == "gold"}
    print(f"\n  Рёбер через границу: {len(rows)}, из них в Silver: {len(holes)}")
    print(f"  Интерфейс по рёбрам монолита: {', '.join(sorted(interface))}")
    for name, dep in holes:
        print(f"  Разрешение дыры: {name} переведён с {dep} на fct_orders —")
        print("    Silver остаётся private, наружу торчит только контракт Gold")
    # fct_orders в интерфейсе не из-за монолита, а из-за закрытой дыры
    if holes:
        interface.add("fct_orders")
    interface = sorted(interface)
    print(f"  Публичный интерфейс platform после разреза: {', '.join(interface)}")
    write_csv(REPORTS_DIR / "day105_107_carve_map.csv",
              ["finance_model", "monolith_dependency", "layer", "verdict"], rows)
    return {"cross_edges": len(rows), "holes": len(holes), "interface": interface}


def step2_platform():
    banner("STEP 2", "platform: сборка и публичный интерфейс")
    MESH_DB.unlink(missing_ok=True)
    t = time.perf_counter()
    _, out = dbt(PLATFORM, "build")
    secs = time.perf_counter() - t
    print(f"  dbt build platform: {dbt_summary(out)}  ({secs:.1f} с)")

    man = json.loads((PLATFORM / "target" / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for n in sorted(man["nodes"].values(), key=lambda n: n["name"]):
        if n["resource_type"] != "model":
            continue
        version = n.get("version") or ""
        contract = n["config"].get("contract", {}).get("enforced", False)
        rows.append((n["name"], version, n["access"], n.get("group") or "", contract, n["relation_name"]))
    for name, v, access, group, contract, rel in rows:
        label = f"{name}.v{v}" if v else name
        print(f"  {label:24} {access:9} contract={'да ' if contract else 'нет'}  {rel}")
    access = Counter(r[2] for r in rows)
    print(f"\n  public={access['public']} protected={access['protected']} private={access['private']}"
          f"  контрактов: {sum(1 for r in rows if r[4])}")
    write_csv(REPORTS_DIR / "day105_107_platform_interface.csv",
              ["model", "version", "access", "group", "contract_enforced", "relation"], rows)
    return {"summary": dbt_summary(out), "secs": secs, "access": dict(access)}


def step3_finance_loom():
    banner("STEP 3", "finance через dbt-loom: только свои узлы")
    t = time.perf_counter()
    _, out = dbt(FINANCE, "build")
    secs = time.perf_counter() - t
    print(f"  dbt build finance: {dbt_summary(out)}  ({secs:.1f} с)")
    built = built_by_package(FINANCE)
    for (kind, pkg), n in sorted(built.items()):
        print(f"    {kind:9} {pkg:9} {n}")
    foreign = sum(n for (_, pkg), n in built.items() if pkg != "finance")
    print(f"  Узлов platform, которые finance собрал сам: {foreign}")

    deprecations = len(re.findall(r"slated for deprecation", out))
    print(f"  Предупреждений о deprecation v1: {deprecations}")

    _, ls_out = dbt(FINANCE, "ls", "--select", "+exposure:finance_board", "--output", "name",
                    "--resource-type", "model", "--resource-type", "seed")
    lineage = [ln.strip() for ln in ls_out.splitlines()
               if re.fullmatch(r"[a-z_]+(\.v\d+)?", ln.strip() or "-")]
    print(f"  Lineage exposure finance_board ({len(lineage)} узлов, через границу проектов):")
    print("    " + ", ".join(lineage))
    return {"summary": dbt_summary(out), "secs": secs, "foreign_built": foreign,
            "own_built": sum(built.values()) - foreign,
            "deprecations": deprecations, "lineage": lineage}


def step4_package_vs_mesh(tmp: Path, loom):
    banner("STEP 4", "Пакет против Mesh: тот же finance, platform как package")
    pkg = tmp / "finance_as_package"
    pkg.mkdir()
    shutil.copytree(FINANCE / "models", pkg / "models")
    shutil.copy(FINANCE / "dbt_project.yml", pkg)
    # Без dbt_loom.config.yml: плагин установлен, но ничего не вставляет.
    # Иначе platform пришла бы дважды — кодом из пакета и узлами из manifest.
    (pkg / "packages.yml").write_text(
        f'packages:\n  - local: "{PLATFORM}"\n', encoding="utf-8")
    db = tmp / "package_mode.duckdb"
    dbt(pkg, "deps", db=db)
    t = time.perf_counter()
    _, out = dbt(pkg, "build", db=db)
    secs = time.perf_counter() - t
    built = built_by_package(pkg)
    foreign = sum(n for (_, p), n in built.items() if p != "finance")
    print(f"  dbt build (package): {dbt_summary(out)}  ({secs:.1f} с)")
    print(f"  Узлов platform, собранных внутри finance: {foreign}")

    # protected: package — «свой», Mesh — чужой
    probe = "select * from {{ ref('platform', 'dim_subscribers') }}"
    with with_probe(probe):
        rc_mesh, _ = dbt(FINANCE, "parse", check=False)
    (pkg / "models" / "zz_mesh_probe.sql").write_text(probe, encoding="utf-8")
    rc_pkg, _ = dbt(pkg, "parse", db=db, check=False)
    print(f"  ref на protected dim_subscribers: Mesh -> {'отбит' if rc_mesh else 'ПРОШЁЛ'},"
          f" package -> {'отбит' if rc_pkg else 'прошёл'}")

    rows = [
        ("код platform внутри finance", "нет, только manifest", "да, весь проект"),
        ("узлов platform собрано finance'ом", loom["foreign_built"], foreign),
        ("своих узлов finance", loom["own_built"], sum(built.values()) - foreign),
        ("время build, с", f"{loom['secs']:.1f}", f"{secs:.1f}"),
        ("ref на protected-модель", "отбит" if rc_mesh else "прошёл", "отбит" if rc_pkg else "прошёл"),
        ("копий fct_orders на складе", 1, 2),
    ]
    print(f"\n  {'':34} {'Mesh (loom)':>20} {'package':>16}")
    for r in rows:
        print(f"  {r[0]:34} {str(r[1]):>20} {str(r[2]):>16}")
    write_csv(REPORTS_DIR / "day105_107_package_vs_mesh.csv", ["metric", "mesh_loom", "package"], rows)
    return {"foreign_pkg": foreign, "protected_mesh_blocked": bool(rc_mesh),
            "protected_pkg_blocked": bool(rc_pkg)}


def step5_governance(tmp: Path):
    banner("STEP 5", "Governance: что Mesh запрещает и как")
    results = []

    def record(probe, expected, caught, how):
        mark = "OK " if caught else "MISS"
        print(f"  [{mark}] {probe:38} ожидали: {expected:8}  {how}")
        results.append((probe, expected, "поймано" if caught else "НЕ поймано", how))

    # 1-2. Доступ
    for model, level in (("stg_orders", "private"), ("dim_subscribers", "protected")):
        with with_probe(f"select * from {{{{ ref('platform', '{model}') }}}}"):
            rc, out = dbt(FINANCE, "parse", check=False)
        msg = re.search(r"which is not allowed because (.+?)\.", out)
        record(f"finance -> {level} {model}", "ошибка", rc != 0,
               msg.group(1) if msg else "без сообщения")

    # 3. Контракт: тип колонки поменялся
    fct = PLATFORM / "models" / "gold" / "fct_orders.sql"
    with patched(fct, "    o.amount,", "    o.amount::VARCHAR AS amount,"):
        rc, out = dbt(PLATFORM, "build", "--select", "fct_orders", check=False)
    mism = re.search(r"\|\s*amount\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|", out)
    record("amount INTEGER -> VARCHAR в fct_orders", "ошибка", rc != 0,
           f"contract: модель {mism.group(1)}, контракт {mism.group(2)}" if mism else "?")

    # 4-5. Breaking change против прошлого состояния: без версии и с версией
    state = tmp / "prod_state"
    state.mkdir()
    shutil.copy(PLATFORM / "target" / "manifest.json", state / "manifest.json")
    gold_yml = PLATFORM / "models" / "gold" / "_gold.yml"

    with patched(fct, "    u.city,\n", ""), \
         patched(gold_yml, "      - name: city\n        data_type: varchar\n", ""):
        rc, out = dbt(PLATFORM, "ls", "--select", "state:modified", "--state", str(state), check=False)
    warned = "Breaking change to contracted, unversioned model" in out
    record("удалить city из fct_orders (без версии)", "warning", warned and rc == 0,
           "WARNING, сборка продолжается" if warned and rc == 0 else f"exit {rc}")

    v1 = PLATFORM / "models" / "gold" / "fct_subscriptions_v1.sql"
    with patched(v1, "    (status = 'churned') AS is_churned,\n", ""), \
         patched(gold_yml, "      - name: is_churned\n        data_type: boolean\n", ""), \
         patched(gold_yml, "exclude: [is_churned, realized_ltv]", "exclude: [realized_ltv]"):
        rc, out = dbt(PLATFORM, "ls", "--select", "state:modified", "--state", str(state), check=False)
    errored = rc != 0 and "breaking change to an enforced contract" in out
    record("удалить is_churned из fct_subscriptions v1", "ошибка", errored,
           "Error: сделай новую версию" if errored else f"exit {rc}")

    # файлы вернулись — проверяем, что проект в исходном состоянии
    dbt(PLATFORM, "parse")
    caught = sum(1 for r in results if r[2] == "поймано")
    print(f"\n  Поймано {caught} из {len(results)}")
    write_csv(REPORTS_DIR / "day105_107_governance.csv", ["probe", "expected", "result", "how"], results)
    return {"caught": caught, "total": len(results)}


def step6_versions():
    banner("STEP 6", "Версии fct_subscriptions: кто где сидит")
    man = json.loads((FINANCE / "target" / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for name in FINANCE_MODELS:
        node = man["nodes"][f"model.finance.{name}"]
        for dep in node["depends_on"]["nodes"]:
            if ".fct_subscriptions." in dep:
                rows.append((name, dep.rsplit(".", 1)[-1]))
    for name, v in rows:
        print(f"  {name:24} -> fct_subscriptions.{v}")

    con = duckdb.connect(str(MESH_DB), read_only=True)
    cols = {}
    for v in ("v1", "v2"):
        cols[v] = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main_gold' AND table_name = ? ORDER BY ordinal_position",
            [f"fct_subscriptions_{v}"]).fetchall()]
    same = fetch_one(con, """
        SELECT count(*) FROM main_gold.fct_subscriptions_v1 a
        JOIN main_gold.fct_subscriptions_v2 b USING (subscription_id)
        WHERE a.realized_ltv = b.ltv_realized""")[0]
    total = fetch_one(con, "SELECT count(*) FROM main_gold.fct_subscriptions_v1")[0]
    con.close()
    only_v1 = [c for c in cols["v1"] if c not in cols["v2"]]
    only_v2 = [c for c in cols["v2"] if c not in cols["v1"]]
    print(f"\n  Только в v1: {only_v1}   только в v2: {only_v2}")
    print(f"  realized_ltv (v1) = ltv_realized (v2): {same} из {total} строк — данные те же,")
    print("  сломан только интерфейс. Поэтому это новая версия, а не правка v1.")
    print("  v1 живёт до deprecation_date 2026-12-31; latest_version = 1,")
    print("  ref() без v= пока получает v1. Переезд — сменить v=1 на v=2 в двух витринах.")
    write_csv(REPORTS_DIR / "day105_107_versions.csv", ["finance_model", "pinned_version"], rows)
    return {"on_v1": sum(1 for r in rows if r[1] == "v1"),
            "on_v2": sum(1 for r in rows if r[1] == "v2"),
            "only_v1": only_v1, "only_v2": only_v2}


def step7_parity(tmp: Path):
    banner("STEP 7", "Паритет: finance против монолита")
    # Копия называется analytics.duckdb не случайно: хуки Elementary
    # обращаются к каталогу по имени, а имя каталога DuckDB = имя файла.
    mono_dir = tmp / "mono"
    mono_dir.mkdir()
    mono_db = mono_dir / "analytics.duckdb"
    shutil.copy(MONOLITH_DB, mono_db)
    (tmp / "profiles.yml").write_text(
        "analytics:\n  target: dev\n  outputs:\n    dev:\n"
        f"      type: duckdb\n      path: \"{mono_db}\"\n      schema: main\n",
        encoding="utf-8")
    target = ("--target-path", str(tmp / "mono_target"))
    selector = [f"+{m}" for m in FINANCE_MODELS]
    t = time.perf_counter()
    dbt(MONOLITH, "seed", *target, "--select",
        "raw_orders", "raw_users", "raw_subscriptions", "raw_saas_users", profiles=tmp)
    # run, а не build: build по eager indirect selection тащит тест
    # test_no_orphan_orders (родитель stg_orders в выборке), а второй
    # его родитель stg_users в выборку не входит и в копии не собран.
    _, out = dbt(MONOLITH, "run", *target, "--select", *selector, profiles=tmp)
    print(f"  Монолит на копии: {dbt_summary(out)}  ({time.perf_counter() - t:.1f} с)")

    con = duckdb.connect()
    con.execute(f"ATTACH '{mono_db}' AS mono (READ_ONLY)")
    con.execute(f"ATTACH '{MESH_DB}' AS mesh (READ_ONLY)")
    rows = []
    for name in FINANCE_MODELS:
        a, b = f"mono.main_gold.{name}", f"mesh.main_finance.{name}"
        only_mono, only_mesh, n_mono, n_mesh = fetch_one(con, f"""
            SELECT (SELECT count(*) FROM (SELECT * FROM {a} EXCEPT ALL SELECT * FROM {b})),
                   (SELECT count(*) FROM (SELECT * FROM {b} EXCEPT ALL SELECT * FROM {a})),
                   (SELECT count(*) FROM {a}), (SELECT count(*) FROM {b})""")
        rows.append((name, n_mono, n_mesh, only_mono, only_mesh))
        ok = "OK  " if only_mono == only_mesh == 0 else "DIFF"
        print(f"  [{ok}] {name:24} строк {n_mono:>4} / {n_mesh:>4}   "
              f"только в монолите {only_mono}, только в mesh {only_mesh}")
    con.close()
    diffs = sum(r[3] + r[4] for r in rows)
    print(f"\n  Расхождений всего: {diffs}. monthly_revenue_pivot читает другой источник")
    print("  (fct_orders вместо stg_orders) и всё равно совпал — фильтр completed")
    print("  уже живёт в Silver, а LEFT JOIN с stg_users не размножает строки.")
    write_csv(REPORTS_DIR / "day105_107_parity.csv",
              ["model", "rows_monolith", "rows_mesh", "only_in_monolith", "only_in_mesh"], rows)
    return {"diffs": diffs, "models": len(rows)}


SQL_23 = """-- snowflake_setup/23_dynamic_tables_mesh.sql
-- Days 105-107: Dynamic Tables + dbt Mesh на уровне аккаунта Snowflake
-- Не выполнялся: Snowflake-аккаунта нет. Запускать по блокам.

-- ══ 1. MESH = ГРАНИЦА ВЛАДЕНИЯ, НЕ ПАПКИ ═════════════════════
--
-- В dbt_mesh/ оба проекта пишут в один файл DuckDB. В Snowflake
-- у каждого проекта своя база и своя роль: platform публикует GOLD,
-- finance читает его и пишет только в свою базу.
--
--   проект     база         роль-писатель   читает
--   ────────   ──────────   ─────────────   ────────────────────
--   platform   PLATFORM     PLATFORM_DBT    BRONZE
--   finance    FINANCE      FINANCE_DBT     PLATFORM.GOLD (public)
--
-- access: public в dbt — обещание. Грант SELECT на PLATFORM.GOLD —
-- то, что реально пускает. Silver (private) finance'у не грантится:
-- без гранта ref() не спасёт, даже если кто-то обойдёт dbt-loom.

USE ROLE SECURITYADMIN;
CREATE ROLE IF NOT EXISTS PLATFORM_DBT;
CREATE ROLE IF NOT EXISTS FINANCE_DBT;

USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS PLATFORM;
CREATE SCHEMA  IF NOT EXISTS PLATFORM.SILVER;
CREATE SCHEMA  IF NOT EXISTS PLATFORM.GOLD;
CREATE DATABASE IF NOT EXISTS FINANCE;
CREATE SCHEMA  IF NOT EXISTS FINANCE.MARTS;

GRANT OWNERSHIP ON SCHEMA PLATFORM.SILVER TO ROLE PLATFORM_DBT COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA PLATFORM.GOLD   TO ROLE PLATFORM_DBT COPY CURRENT GRANTS;
GRANT OWNERSHIP ON SCHEMA FINANCE.MARTS   TO ROLE FINANCE_DBT  COPY CURRENT GRANTS;

-- finance видит только публичный слой platform
GRANT USAGE  ON DATABASE PLATFORM               TO ROLE FINANCE_DBT;
GRANT USAGE  ON SCHEMA   PLATFORM.GOLD          TO ROLE FINANCE_DBT;
GRANT SELECT ON ALL    TABLES IN SCHEMA PLATFORM.GOLD TO ROLE FINANCE_DBT;
GRANT SELECT ON FUTURE TABLES IN SCHEMA PLATFORM.GOLD TO ROLE FINANCE_DBT;

-- Проверка: у finance нет доступа к Silver
SHOW GRANTS TO ROLE FINANCE_DBT;
-- ожидается: USAGE на PLATFORM и PLATFORM.GOLD, SELECT на таблицы GOLD,
-- ни одной строки про PLATFORM.SILVER

-- Версии модели в Snowflake — это две таблицы рядом:
--   PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V1, PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V2
-- Удобно держать view без суффикса на latest_version, чтобы BI не
-- переписывать при каждом релизе (в dbt — post-hook или macro):
CREATE OR REPLACE VIEW PLATFORM.GOLD.FCT_SUBSCRIPTIONS
    AS SELECT * FROM PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V1;

-- ══ 2. DYNAMIC TABLES ═══════════════════════════════════════
--
-- Dynamic Table — декларация «результат + допустимое отставание».
-- Когда и как обновлять (incremental или full), решает Snowflake.
--
--                       dbt incremental      Dynamic Table
--   кто запускает       оркестратор (cron)   Snowflake по target_lag
--   логика дельты       is_incremental()     выводит сам из запроса
--   свежесть            расписание           target_lag, напр. 1 минута
--   цена                warehouse на прогон  warehouse на каждый refresh
--   цепочки             DAG в dbt/Dagster    DOWNSTREAM lag по графу DT
--   тесты dbt           до публикации        после: DT уже обновилась

USE ROLE FINANCE_DBT;
USE WAREHOUSE TRANSFORM_WH;

CREATE OR REPLACE DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE
    TARGET_LAG   = '15 minutes'
    WAREHOUSE    = TRANSFORM_WH
    REFRESH_MODE = INCREMENTAL
AS
SELECT DATE_TRUNC('month', start_date) AS month,
       plan,
       COUNT(*)  AS new_subs,
       SUM(mrr)  AS new_mrr
FROM PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V2
GROUP BY 1, 2;

-- Почему REFRESH_MODE задан явно: при AUTO Snowflake молча выбирает
-- FULL, если запрос не поддерживает инкремент (некоторые оконные
-- функции, недетерминированные выражения). Явный INCREMENTAL упадёт
-- на создании — лучше узнать сразу, чем по счёту за warehouse.
SHOW DYNAMIC TABLES LIKE 'MART_MRR_LIVE' IN SCHEMA FINANCE.MARTS;
-- колонки: target_lag, refresh_mode, refresh_mode_reason, scheduling_state

-- Промежуточная DT: TARGET_LAG = DOWNSTREAM — обновляется, только
-- когда её требует нижняя DT. Своего расписания нет.
CREATE OR REPLACE DYNAMIC TABLE FINANCE.MARTS.SUBS_ACTIVE
    TARGET_LAG = DOWNSTREAM
    WAREHOUSE  = TRANSFORM_WH
AS
SELECT * FROM PLATFORM.GOLD.FCT_SUBSCRIPTIONS_V2 WHERE end_date IS NULL;

-- История обновлений: сколько строк, сколько длилось, каким способом
SELECT name, state, refresh_action, refresh_trigger,
       statistics:numInsertedRows::INT AS inserted,
       statistics:numDeletedRows::INT  AS deleted,
       DATEDIFF('second', refresh_start_time, refresh_end_time) AS secs
FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY(
    NAME_PREFIX => 'FINANCE.MARTS.'))
ORDER BY refresh_start_time DESC
LIMIT 20;

-- Фактическое отставание против обещанного
SELECT name, target_lag_sec, mean_lag_sec, maximum_lag_sec, time_within_target_lag_ratio
FROM TABLE(INFORMATION_SCHEMA.DYNAMIC_TABLE_GRAPH_HISTORY())
WHERE qualified_name ILIKE 'FINANCE.MARTS.%';

-- Остановить обновления (например, на время backfill в platform)
ALTER DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE SUSPEND;
ALTER DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE RESUME;
-- Ручной refresh вне расписания
ALTER DYNAMIC TABLE FINANCE.MARTS.MART_MRR_LIVE REFRESH;

-- В dbt это та же модель: dbt_mesh/finance/models/mart_mrr_live.sql,
-- materialized='dynamic_table', target_lag, snowflake_warehouse.
-- dbt создаёт DT и дальше её не гоняет — dbt run только меняет
-- определение, если SQL поменялся.

-- ══ 3. ОЧИСТКА ══════════════════════════════════════════════
-- DROP DYNAMIC TABLE IF EXISTS FINANCE.MARTS.MART_MRR_LIVE;
-- DROP DYNAMIC TABLE IF EXISTS FINANCE.MARTS.SUBS_ACTIVE;
"""


def step8_sql_and_summary(carve, platform, loom, pkg, gov, versions, parity):
    banner("STEP 8", "SQL под Snowflake + итог")
    sql_path = SNOWFLAKE_DIR / "23_dynamic_tables_mesh.sql"
    write_utf8(sql_path, SQL_23)
    rows = [
        ("cross_project_edges", carve["cross_edges"]),
        ("interface_holes_fixed", carve["holes"]),
        ("platform_public_models", platform["access"].get("public", 0)),
        ("platform_protected_models", platform["access"].get("protected", 0)),
        ("platform_private_models", platform["access"].get("private", 0)),
        ("platform_build", platform["summary"]),
        ("finance_build", loom["summary"]),
        ("platform_nodes_built_by_finance_mesh", loom["foreign_built"]),
        ("platform_nodes_built_by_finance_package", pkg["foreign_pkg"]),
        ("protected_blocked_mesh", pkg["protected_mesh_blocked"]),
        ("protected_blocked_package", pkg["protected_pkg_blocked"]),
        ("governance_probes_caught", f"{gov['caught']}/{gov['total']}"),
        ("finance_models_on_v1", versions["on_v1"]),
        ("finance_models_on_v2", versions["on_v2"]),
        ("v1_deprecation_warnings", loom["deprecations"]),
        ("parity_models", parity["models"]),
        ("parity_diff_rows", parity["diffs"]),
    ]
    path = write_csv(REPORTS_DIR / "day105_107_summary.csv", ["metric", "value"], rows)

    print("""
  На собеседовании:
    "Чем dbt Mesh отличается от пакетов?"
    -> Пакет — это копия исходного кода: downstream собирает upstream-модели
       у себя, protected-модели ему доступны, и любое изменение upstream
       приезжает при dbt deps. Mesh — ссылка на уже собранные таблицы
       через manifest: downstream строит только своё, видит только public,
       а контракт и версии делают интерфейс явным. В dbt Core cross-project
       ref нативно не работает — это dbt platform Enterprise, в Core его
       закрывают плагином dbt-loom.

    "Как поменять колонку в модели, на которую смотрят другие команды?"
    -> Если модель контрактная и версионированная — новой версией: v2 рядом
       с v1, deprecation_date на v1, потребители переезжают сами. dbt с
       --state ловит breaking change и падает с ошибкой. Подвох: у
       контрактной, но НЕ версионированной модели это только warning —
       поэтому публичные модели стоит версионировать сразу.

    "Dynamic Table или dbt incremental?"
    -> DT — когда нужна свежесть в минутах и запрос простой: Snowflake сам
       решает, когда обновлять, оркестратор не нужен. Incremental — когда
       нужны тесты до публикации, сложная логика дельты или контроль
       стоимости расписанием. DT тестируется уже после обновления.""")
    return sql_path, path


def main():
    t0 = time.perf_counter()
    try:
        import dbt_loom  # noqa: F401
    except ImportError:
        raise SystemExit("Нет dbt-loom: uv pip install --python ~/.venvs/ae/bin/python dbt-loom")
    for p in (MONOLITH_MANIFEST, MONOLITH_DB):
        if not p.exists():
            raise SystemExit(f"Нет {p} — нужен собранный монолит из прошлых уроков")

    seeds_before = seeds_fingerprint()
    with tempfile.TemporaryDirectory(prefix="mesh_") as tmp_str:
        tmp = Path(tmp_str)
        carve = step1_carve_map()
        platform = step2_platform()
        loom = step3_finance_loom()
        pkg = step4_package_vs_mesh(tmp, loom)
        gov = step5_governance(tmp)
        versions = step6_versions()
        parity = step7_parity(tmp)
        sql_path, summary_path = step8_sql_and_summary(
            carve, platform, loom, pkg, gov, versions, parity)
    PROBE.unlink(missing_ok=True)
    if seeds_fingerprint() != seeds_before:
        raise SystemExit("  FAIL: CSV в dbt_analytics/data изменились — git diff dbt_analytics/data")

    print("\n" + SEP)
    print(f"  ALL DONE  ({time.perf_counter() - t0:.0f} с)")
    print(SEP)
    print(f"""
Артефакты:
  dbt_mesh/platform, dbt_mesh/finance, dbt_mesh/mesh.duckdb
  {sql_path.relative_to(PROJECT_ROOT)}
  reports/day105_107_carve_map.csv
  reports/day105_107_platform_interface.csv
  reports/day105_107_package_vs_mesh.csv
  reports/day105_107_governance.csv
  reports/day105_107_versions.csv
  reports/day105_107_parity.csv
  {summary_path.relative_to(PROJECT_ROOT)}

Что осталось несделанным честно:
  Монолит dbt_analytics не разрезан, а раздвоен: 12 моделей теперь
  живут и там, и в dbt_mesh. Удалить их из монолита = переписать
  Dagster, metrics_api, CI и старые уроки на новые схемы — отдельная
  миграция. Сейчас dbt_mesh — рабочий образец разреза с проверенным
  паритетом, а не замена монолита.
  Оба проекта в одном файле DuckDB, грантов нет — изоляция только
  на уровне dbt (access), не склада. Складская часть — скрипт 23.
  Dynamic Tables не запускались: Snowflake-аккаунта нет.

Next steps:
  1. Поиграть: в finance поменять v=1 на v=2 в mart_ltv и посмотреть,
     на какой колонке упадёт — realized_ltv в v2 переименована
  2. Days 108-110 — Airbyte Advanced: custom connector на Python CDK
  3. Концепты в базу: /ae-concept dbt Mesh, Model Contracts, Model Versions,
     Dynamic Tables

Git:
  git add lesson105_107.py dbt_mesh/ snowflake_setup/23_dynamic_tables_mesh.sql \\
          reports/day105_107_* requirements.txt .gitignore
  git commit -m "feat: Days 105-107 dbt Mesh — platform + finance, dbt-loom, contracts, versions"
""")


if __name__ == "__main__":
    main()
