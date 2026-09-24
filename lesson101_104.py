#!/usr/bin/env python3
"""
lesson101_104.py — Days 101-104: Medallion Architecture

Запуск:
    python lesson101_104.py

Открывает Неделю 14 (Data Architecture Patterns). В отличие от дней
91-100 здесь почти ничего не симулируется: Medallion — это не фича
Snowflake, а договорённость о слоях, и она целиком живёт в dbt-проекте.

Перестройка dbt_analytics уже лежит в коде (ветка day101-104-medallion):
  - dbt_project.yml: staging -> +schema: silver, marts/metrics -> gold,
    seeds и snapshots помечены тегом bronze
  - macros/generate_schema_name.sql: main_silver / main_gold в dev,
    ровно SILVER / GOLD в prod
  - models/staging/stg_snap_customers.sql: Silver-обёртка над snapshot,
    dim_customers* больше не читают Bronze напрямую
  - 5 Snowflake-only моделей выключены вне Snowflake
  - metrics_api читает main_gold, у него появилась exposure
  - Dagster: ключи ассетов не меняются, слой — это группа

Урок проверяет, что перестройка настоящая:
  1. Аудит склада ДО сборки: что физически лежит в main
  2. Контракт слоёв по manifest.json + негативная проба
  3. dbt build Silver + Gold в новые схемы
  4. Миграция без потерь: старая копия в main против новой в Gold
  5. Сироты: старые объекты в main, которые больше никто не обновляет
  6. Главное свойство: снести Silver и Gold, пересобрать из Bronze,
     получить те же данные
  7. SQL под реальный Snowflake: схемы, retention, RBAC по слоям
  8. CSV в reports/ + блок «На собеседовании»

Что здесь хуже оригинала — честно:
  Bronze не переносится в отдельную схему. Сырые таблицы остаются
  в main и raw, потому что их туда пишут загрузчики: seeds, lesson46,
  CI-скрипт, Dagster ingest. Смена схемы Bronze — это смена destination
  у загрузчика, отдельная миграция. dbt Bronze только объявляет.
  Гранты по слоям в DuckDB не существуют — это только скрипт 22.
"""

import csv
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).parent
DBT_PROJECT = PROJECT_ROOT / "dbt_analytics"
DB_PATH = DBT_PROJECT / "analytics.duckdb"
MANIFEST = DBT_PROJECT / "target" / "manifest.json"
SNOWFLAKE_DIR = PROJECT_ROOT / "snowflake_setup"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# dbt Core из того же venv, что и python: в PATH может стоять
# dbt Fusion, а он не умеет DuckDB (грабли дня 81-85).
DBT = Path(sys.executable).parent / "dbt"

TODAY = datetime.now().strftime("%Y-%m-%d")
SEP = "=" * 62

OLD_SCHEMA = "main"
SILVER = "main_silver"
GOLD = "main_gold"
LAYER_ORDER = {"bronze": 0, "silver": 1, "gold": 2}

# Функции, из-за которых модель даёт разный результат при каждой
# сборке. Такие модели не могут совпасть побайтово с прошлой сборкой,
# и это не баг миграции.
VOLATILE = re.compile(r"current_timestamp|current_date|now\(\)|getdate\(\)", re.I)

BUILD_SELECTOR = ("--select", "tag:silver", "tag:gold", "--exclude", "resource_type:snapshot")

PROBE = DBT_PROJECT / "models" / "marts" / "zz_medallion_probe.sql"


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


def dbt(*args: str) -> str:
    """Запуск dbt. Соединение DuckDB в этот момент должно быть закрыто:
    файл берёт эксклюзивную блокировку на запись."""
    proc = subprocess.run(
        [str(DBT), *args], cwd=DBT_PROJECT, capture_output=True, text=True
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        print("\n".join(out.splitlines()[-30:]))
        raise SystemExit(f"  FAIL: dbt {' '.join(args)} -> exit {proc.returncode}")
    return out


def dbt_summary(out: str) -> str:
    m = re.search(r"Done\. (PASS=\d+ WARN=\d+ ERROR=\d+ SKIP=\d+.*TOTAL=\d+)", out)
    return m.group(1) if m else "?"


def layer_of_name(name: str) -> str:
    """Слой по соглашению об именах — для объектов, которых нет в manifest."""
    if name.startswith(("raw_", "airbyte_raw_", "_airbyte_raw_", "snap_")):
        return "bronze"
    if name.startswith("stg_"):
        return "silver"
    if name.startswith(("fct_", "dim_", "mart_", "metrics_", "monthly_", "metricflow_")):
        return "gold"
    return "unknown"


def list_objects(con, schemas) -> list[tuple[str, str, str]]:
    placeholders = ", ".join("?" for _ in schemas)
    return con.execute(
        f"""SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema IN ({placeholders})
            ORDER BY 1, 2""",
        list(schemas),
    ).fetchall()


def fetch_one(con, sql: str, params=None) -> tuple:
    """fetchone() в DuckDB типизирован как tuple | None. Для агрегата
    без GROUP BY строка есть всегда, но Pylance этого не знает и
    подсвечивает [0] и распаковку. Проверка делает контракт явным."""
    row = con.execute(sql, params).fetchone() if params else con.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"запрос не вернул строк: {sql[:60]}")
    return row


def fingerprint(con, relation: str) -> tuple[int, str]:
    """Строк + сумма хешей строк. Сумма не зависит от порядка строк,
    поэтому ORDER BY в модели не влияет на сравнение."""
    rows, h = fetch_one(
        con, f"SELECT count(*), coalesce(sum(hash(t)), 0)::VARCHAR FROM {relation} t"
    )
    return rows, h


def diff_columns(con, old_rel: str, new_rel: str, columns: list[str]) -> list[str]:
    diffs = []
    for col in columns:
        a = fetch_one(con, f'SELECT sum(hash("{col}"))::VARCHAR FROM {old_rel}')[0]
        b = fetch_one(con, f'SELECT sum(hash("{col}"))::VARCHAR FROM {new_rel}')[0]
        if a != b:
            diffs.append(col)
    return diffs


def columns_of(con, schema: str, table: str) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = ? AND table_name = ?
               ORDER BY ordinal_position""",
            [schema, table],
        ).fetchall()
    ]


# ═══════════════════════════════════════════════════════════
#  Manifest -> граф слоёв
# ═══════════════════════════════════════════════════════════

def load_graph():
    """Узлы проекта со слоем и рёбра между ними.

    Слой берётся из тегов, которые проставил dbt_project.yml, а не
    из имени папки: если кто-то положит модель не в ту папку, тег
    покажет, куда она на самом деле попала.
    """
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # Нестабильность прячется в макросах: fct_orders_enriched зовёт
    # days_since(), а CURRENT_DATE живёт внутри макроса. Регулярка по
    # raw_code модели его не видит, поэтому смотрим и на её макросы.
    volatile_macros = {
        uid for uid, mac in m["macros"].items()
        if mac.get("package_name") == "analytics_project"
        and VOLATILE.search(mac.get("macro_sql", ""))
    }
    nodes = {}
    for uid, n in m["nodes"].items():
        if n.get("package_name") != "analytics_project":
            continue
        rt = n["resource_type"]
        tags = n.get("tags", [])
        if rt == "seed":
            layer = "bronze"
        elif rt == "snapshot":
            # по умолчанию Bronze, но snapshot витрины — это история Gold
            layer = next((t for t in ("bronze", "silver", "gold") if t in tags), "bronze")
        elif rt == "model":
            layer = next((t for t in ("silver", "gold") if t in tags), "untagged")
        else:
            continue
        macros = set(n.get("depends_on", {}).get("macros", []))
        nodes[uid] = {
            "name": n["name"],
            "type": rt,
            "layer": layer,
            "schema": n["schema"],
            "deps": n.get("depends_on", {}).get("nodes", []),  # у seeds ключа nodes нет
            "volatile": bool(VOLATILE.search(n.get("raw_code", ""))
                             or macros & volatile_macros),
            "materialized": n["config"].get("materialized"),
        }
    for uid, s in m["sources"].items():
        if s.get("package_name") == "analytics_project":
            nodes[uid] = {"name": f"{s['source_name']}.{s['name']}", "type": "source",
                          "layer": "bronze", "schema": s["schema"], "deps": [],
                          "volatile": False, "materialized": None}
    disabled = {
        d["name"]
        for items in m.get("disabled", {}).values()
        for d in items
        if d.get("resource_type") == "model" and d.get("package_name") == "analytics_project"
    }
    return nodes, disabled


def check_contract(nodes) -> tuple[dict, list]:
    """Правила Medallion на рёбрах графа.

    Разрешено:  bronze -> silver, silver -> silver, silver -> gold, gold -> gold,
                bronze -> bronze (snapshot поверх source)
    Запрещено:  bronze -> gold  (Gold в обход очистки)
                gold -> silver, * -> bronze (поток против течения)
    """
    matrix, violations = {}, []
    for uid, n in nodes.items():
        for dep in n["deps"]:
            if dep not in nodes:
                continue
            src, dst = nodes[dep]["layer"], n["layer"]
            matrix[(src, dst)] = matrix.get((src, dst), 0) + 1
            reason = None
            if "untagged" in (src, dst):
                reason = "модель без слоя"
            elif src == "bronze" and dst == "gold":
                reason = "Gold читает Bronze в обход Silver"
            elif LAYER_ORDER[src] > LAYER_ORDER[dst]:
                reason = f"поток против течения: {src} -> {dst}"
            if reason:
                violations.append((nodes[dep]["name"], n["name"], src, dst, reason))
    return matrix, violations


# ═══════════════════════════════════════════════════════════
#  STEP 1 — аудит склада до сборки
# ═══════════════════════════════════════════════════════════

def step1_audit_warehouse():
    banner("STEP 1", "Аудит склада: что физически лежит по схемам")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    objs = list_objects(con, ("main", "raw", "snapshots", SILVER, GOLD))
    con.close()

    counts: dict[tuple[str, str], int] = {}
    for schema, name, _ in objs:
        key = (schema, layer_of_name(name))
        counts[key] = counts.get(key, 0) + 1

    schemas = sorted({s for s, _ in counts})
    layers = ["bronze", "silver", "gold", "unknown"]
    print(f"\n  {'schema':<14}" + "".join(f"{l:>9}" for l in layers))
    for s in schemas:
        print(f"  {s:<14}" + "".join(f"{counts.get((s, l), 0):>9}" for l in layers))

    mixed = [s for s in schemas if sum(1 for l in layers[:3] if counts.get((s, l))) > 1]
    if mixed:
        print(f"\n  Схемы, где смешаны слои: {', '.join(mixed)}")
        print("  В одной схеме лежат сырьё, очищенные вьюхи и витрины. Грант")
        print("  «BI читает только витрины» на такую схему выдать нельзя: он")
        print("  откроет и сырые таблицы с email клиентов.")
    else:
        print("\n  Смешанных схем нет — перестройка уже применялась ранее.")

    rows = [(s, l, counts.get((s, l), 0)) for s in schemas for l in layers]
    write_csv(REPORTS_DIR / "day101_104_audit_before.csv", ["schema", "layer", "objects"], rows)
    return counts


# ═══════════════════════════════════════════════════════════
#  STEP 2 — контракт слоёв
# ═══════════════════════════════════════════════════════════

def step2_contract():
    banner("STEP 2", "Контракт слоёв по manifest.json")
    dbt("parse")
    nodes, disabled = load_graph()
    matrix, violations = check_contract(nodes)

    by_layer: dict[str, int] = {}
    for n in nodes.values():
        by_layer[n["layer"]] = by_layer.get(n["layer"], 0) + 1
    print("\n  Узлов по слоям: " + ", ".join(f"{k}={v}" for k, v in sorted(by_layer.items())))
    print(f"  Выключено вне Snowflake: {len(disabled)} ({', '.join(sorted(disabled))})")

    print("\n  Рёбра графа (откуда -> куда):")
    for (src, dst), cnt in sorted(matrix.items(), key=lambda x: (LAYER_ORDER.get(x[0][0], 9), LAYER_ORDER.get(x[0][1], 9))):
        print(f"    {src:>7} -> {dst:<7} {cnt:>3}")
    print(f"\n  Нарушений: {len(violations)}")
    for v in violations:
        print(f"    {v[0]} -> {v[1]}: {v[4]}")

    # Негативная проба: проверка, которая ни разу не краснела,
    # ничего не доказывает. Кладём модель-нарушителя и смотрим,
    # поймает ли её контракт.
    print("\n  Негативная проба: Gold-модель читает source напрямую")
    try:
        PROBE.write_text(
            "-- vremennyy fayl lesson101_104.py, dolzhen byt udalen\n"
            "SELECT * FROM {{ source('saas_raw', 'raw_events') }}\n",
            encoding="utf-8",
        )
        dbt("parse")
        probe_nodes, _ = load_graph()
        _, probe_violations = check_contract(probe_nodes)
        caught = [v for v in probe_violations if v[1] == "zz_medallion_probe"]
        print(f"    поймано нарушений пробы: {len(caught)} из 1")
        for v in caught:
            print(f"    {v[0]} -> {v[1]}: {v[4]}")
    finally:
        PROBE.unlink(missing_ok=True)
        dbt("parse")
    if len(caught) != 1:
        raise SystemExit("  FAIL: контракт не поймал подложенное нарушение")

    rows = [(v[0], v[1], v[2], v[3], v[4]) for v in violations]
    write_csv(REPORTS_DIR / "day101_104_contract.csv",
              ["upstream", "downstream", "from_layer", "to_layer", "reason"],
              rows or [("-", "-", "-", "-", "0 нарушений")])
    return nodes, disabled, violations, len(caught)


# ═══════════════════════════════════════════════════════════
#  STEP 3 — сборка в новые схемы
# ═══════════════════════════════════════════════════════════

def step3_build():
    banner("STEP 3", "dbt build: Silver + Gold в новые схемы")
    # Bronze НЕ пересобирается: seeds перезаписали бы raw_* из CSV
    # и стёрли бы всё, что загрузчики дописали после. Snapshot'ы
    # исключены целиком, в том числе Gold-snapshot snap_subscribers:
    # каждый его запуск — это новая точка истории, а не пересборка.
    t0 = time.perf_counter()
    out = dbt("build", *BUILD_SELECTOR)
    sec = time.perf_counter() - t0
    summary = dbt_summary(out)
    print(f"\n  {summary}  ({sec:.1f} с)")

    con = duckdb.connect(str(DB_PATH), read_only=True)
    for schema in (SILVER, GOLD):
        objs = list_objects(con, (schema,))
        kinds: dict[str, int] = {}
        for _, _, t in objs:
            kinds[t] = kinds.get(t, 0) + 1
        print(f"  {schema:<12} {len(objs):>3} объектов  " +
              ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    con.close()
    return summary, sec


# ═══════════════════════════════════════════════════════════
#  STEP 4 — миграция без потерь
# ═══════════════════════════════════════════════════════════

def step4_migration_diff(nodes):
    banner("STEP 4", "Старая копия в main против новой в Silver/Gold")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    old = {name for _, name, _ in list_objects(con, (OLD_SCHEMA,))}

    rows, stats = [], {"same": 0, "volatile": 0, "changed": 0, "new": 0}
    for n in sorted(nodes.values(), key=lambda x: x["name"]):
        if n["type"] != "model":
            continue
        name, schema = n["name"], n["schema"]
        new_rel = f"{schema}.{name}"
        if name not in old:
            stats["new"] += 1
            rows.append((name, schema, "", "", "new", "модели не было до перестройки"))
            continue
        old_rel = f"{OLD_SCHEMA}.{name}"
        try:
            o_rows, o_hash = fingerprint(con, old_rel)
        except duckdb.Error as e:
            rows.append((name, schema, "", "", "old_broken", str(e).splitlines()[0]))
            continue
        n_rows, n_hash = fingerprint(con, new_rel)
        if (o_rows, o_hash) == (n_rows, n_hash):
            verdict, note = "same", ""
        else:
            cols = [c for c in columns_of(con, schema, name) if c in columns_of(con, OLD_SCHEMA, name)]
            diff = diff_columns(con, old_rel, new_rel, cols) if o_rows == n_rows else []
            if n["volatile"] and o_rows == n_rows:
                verdict, note = "volatile", "разошлись только " + ", ".join(diff)
            else:
                verdict = "changed"
                note = f"строк {o_rows} -> {n_rows}" + (f"; колонки {', '.join(diff)}" if diff else "")
        stats[verdict] += 1
        rows.append((name, schema, o_rows, n_rows, verdict, note))
    con.close()

    print(f"\n  {'модель':<26}{'схема':<13}{'было':>7}{'стало':>7}  вердикт")
    for r in rows:
        print(f"  {r[0]:<26}{r[1]:<13}{str(r[2]):>7}{str(r[3]):>7}  {r[4]}  {r[5]}")
    print("\n  " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    print("  volatile — в SQL модели есть CURRENT_TIMESTAMP/CURRENT_DATE:")
    print("  старая копия собрана в другой день, разница в колонке времени")
    print("  сборки, а не в данных. changed — вот это надо разбирать руками.")

    write_csv(REPORTS_DIR / "day101_104_migration_diff.csv",
              ["model", "new_schema", "rows_old", "rows_new", "verdict", "note"], rows)
    return stats


# ═══════════════════════════════════════════════════════════
#  STEP 5 — сироты
# ═══════════════════════════════════════════════════════════

def step5_orphans(nodes, disabled):
    banner("STEP 5", "Сироты в main: объекты, которые больше никто не обновляет")
    # dbt не удаляет старую таблицу, когда модель меняет схему. main.fct_orders
    # останется навсегда и будет выглядеть живой: те же колонки, те же строки
    # на момент переезда. Любой, кто читает её по имени, дальше получает
    # данные, которые застыли. Именно так читал metrics_api до этого урока.
    managed = {n["name"] for n in nodes.values() if n["type"] == "model"} | disabled
    con = duckdb.connect(str(DB_PATH))
    objs = list_objects(con, (OLD_SCHEMA,))
    orphans = [(n, t) for _, n, t in objs if n in managed]
    bronze = [n for _, n, _ in objs if layer_of_name(n) == "bronze"]
    foreign = [n for _, n, _ in objs if n not in managed and layer_of_name(n) != "bronze"]

    print(f"\n  В {OLD_SCHEMA}: {len(objs)} объектов")
    print(f"    Bronze (остаётся, это зона загрузчиков): {len(bronze)}")
    print(f"    сироты dbt-моделей (удаляются):           {len(orphans)}")
    print(f"    чужие, не из dbt (не трогаем):            {len(foreign)}  {', '.join(foreign)}")

    # Вьюхи первыми: старая main.fct_orders_star ссылается на main.fct_orders_enriched
    for name, t in sorted(orphans, key=lambda x: x[1] != "VIEW"):
        kind = "VIEW" if t == "VIEW" else "TABLE"
        con.execute(f"DROP {kind} IF EXISTS {OLD_SCHEMA}.{name}")
    left = list_objects(con, (OLD_SCHEMA,))
    con.close()
    print(f"\n  Удалено: {len(orphans)}. В {OLD_SCHEMA} осталось {len(left)}: "
          f"{len(bronze)} Bronze + {len(foreign)} чужих")

    rows = [(n, t, "dropped") for n, t in orphans] + [(n, "", "bronze_kept") for n in bronze] \
        + [(n, "", "foreign_kept") for n in foreign]
    write_csv(REPORTS_DIR / "day101_104_orphans.csv", ["object", "type", "action"], rows)
    return len(orphans), len(bronze), foreign


# ═══════════════════════════════════════════════════════════
#  STEP 6 — пересобрать из Bronze
# ═══════════════════════════════════════════════════════════

def gold_silver_fingerprints(nodes):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    fp = {}
    for n in nodes.values():
        if n["type"] == "model":
            rel = f"{n['schema']}.{n['name']}"
            fp[n["name"]] = (fingerprint(con, rel), columns_of(con, n["schema"], n["name"]))
    con.close()
    return fp


def step6_rebuild_from_bronze(nodes):
    banner("STEP 6", "DROP Silver + Gold -> пересборка из Bronze -> сверка")
    before = gold_silver_fingerprints(nodes)

    con = duckdb.connect(str(DB_PATH))
    for schema in (GOLD, SILVER):
        con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    gone = fetch_one(
        con,
        "SELECT count(*) FROM information_schema.schemata WHERE schema_name IN (?, ?)",
        [SILVER, GOLD],
    )[0]
    con.close()
    print(f"\n  Схемы {SILVER} и {GOLD} удалены (осталось схем: {gone})")

    t0 = time.perf_counter()
    out = dbt("build", *BUILD_SELECTOR)
    sec = time.perf_counter() - t0
    summary = dbt_summary(out)
    print(f"  Пересборка: {summary}  ({sec:.1f} с)")

    after = gold_silver_fingerprints(nodes)
    rows, same, volatile, broken = [], 0, 0, []
    by_name = nodes_by_name(nodes)
    for name, ((b_rows, b_hash), cols) in sorted(before.items()):
        (a_rows, a_hash), _ = after[name]
        if (b_rows, b_hash) == (a_rows, a_hash):
            same += 1
            rows.append((name, b_rows, a_rows, "same", ""))
        elif b_rows == a_rows and by_name[name]["volatile"]:
            volatile += 1
            rows.append((name, b_rows, a_rows, "volatile", "время сборки"))
        else:
            broken.append(name)
            rows.append((name, b_rows, a_rows, "DIFF", ""))

    print(f"\n  Моделей: {len(before)}  совпали побайтово: {same}  "
          f"volatile: {volatile}  расхождений: {len(broken)}")
    if broken:
        print(f"  РАСХОЖДЕНИЯ: {', '.join(broken)}")

    # Обратная сторона: что НЕ пересобирается
    con = duckdb.connect(str(DB_PATH), read_only=True)
    snap_total = snap_hist = 0
    print("\n  Что не пересобирается — snapshot'ы:")
    for n in sorted(nodes.values(), key=lambda x: x["name"]):
        if n["type"] != "snapshot":
            continue
        total, hist = fetch_one(
            con,
            "SELECT count(*), count(*) FILTER (WHERE dbt_valid_to IS NOT NULL) "
            f"FROM {n['schema']}.{n['name']}",
        )
        snap_total, snap_hist = snap_total + total, snap_hist + hist
        print(f"    {n['name']:<22} слой {n['layer']:<7} версий {total:>4}, закрытых {hist}")
    con.close()
    if snap_hist:
        print(f"  {snap_hist} закрытых версий есть только в snapshot'ах — источник")
        print("  хранит лишь текущее состояние. Снести snapshot как Silver = потерять их.")
    else:
        print("  Закрытых версий пока 0: источники не менялись с первого снимка.")
        print("  Терять сейчас нечего, но первая же смена plan или статуса ляжет")
        print("  только сюда — поэтому snapshot'ы в пересборку не входят.")

    write_csv(REPORTS_DIR / "day101_104_rebuild.csv",
              ["model", "rows_before", "rows_after", "verdict", "note"], rows)
    return {"models": len(before), "same": same, "volatile": volatile,
            "diff": len(broken), "sec": sec, "summary": summary,
            "snap_total": snap_total, "snap_hist": snap_hist}


def nodes_by_name(nodes):
    return {n["name"]: n for n in nodes.values()}


# ═══════════════════════════════════════════════════════════
#  STEP 7 — SQL под реальный Snowflake
# ═══════════════════════════════════════════════════════════

MEDALLION_SQL = """\
-- snowflake_setup/22_medallion_layers.sql
-- Days 101-104: Medallion Architecture на Snowflake
-- Запускать в Worksheet по блокам, роль ACCOUNTADMIN (блок 1) и SECURITYADMIN (блок 3).

-- ══ ЗАЧЕМ СЛОИ — ЭТО СХЕМЫ, А НЕ ПАПКИ ═════════════════════
--
-- Папки в dbt видит только разработчик. Схемы видит Snowflake:
-- на них вешаются гранты, retention и тип таблиц. Поэтому граница
-- слоя — это граница схемы, и у каждого слоя своя цена и свой доступ.
--
--   слой     кто пишет     кто читает           тип схемы   Time Travel
--   ──────   ───────────   ──────────────────   ─────────   ───────────
--   BRONZE   LOADER        TRANSFORMER          permanent   долгий: это
--            (Airbyte)                                      единственная копия
--   SILVER   TRANSFORMER   TRANSFORMER          TRANSIENT   0-1 день: всё
--            (dbt)                                          пересобирается
--   GOLD     TRANSFORMER   REPORTER (BI, API)   permanent   1+ день: откат
--            (dbt)                                          витрины после
--                                                           плохого деплоя

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE COMPUTE_WH;

-- ── 1. Схемы ────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS ANALYTICS;
USE DATABASE ANALYTICS;

-- Bronze: сюда пишет Airbyte (destination namespace = BRONZE).
-- Fail-safe и длинный Time Travel нужны именно здесь: из источника
-- историю не восстановить, а snapshot'ы dbt тоже лежат тут.
CREATE SCHEMA IF NOT EXISTS BRONZE
    DATA_RETENTION_TIME_IN_DAYS = 30;     -- 30 требует Enterprise; на Standard максимум 1

-- Silver: TRANSIENT. Нет Fail-safe (7 дней хранения, за которые
-- платишь), потому что любой объект здесь пересобирается из Bronze
-- одной командой dbt build. Платить за страховку восстановимого — лишнее.
CREATE TRANSIENT SCHEMA IF NOT EXISTS SILVER
    DATA_RETENTION_TIME_IN_DAYS = 1;

-- Gold: permanent. Пересобрать тоже можно, но на это нужно время,
-- а дашборды и API читают его прямо сейчас. Time Travel нужен для
-- быстрого отката: SELECT ... AT(OFFSET => -3600) вместо пересборки.
CREATE SCHEMA IF NOT EXISTS GOLD
    DATA_RETENTION_TIME_IN_DAYS = 7;

-- Таблица в TRANSIENT-схеме наследует TRANSIENT автоматически.
-- Проверка: колонка "options" = TRANSIENT, retention_time = 1.
SHOW SCHEMAS IN DATABASE ANALYTICS;

-- ── 2. Как dbt попадает в эти схемы ─────────────────────────
-- dbt_project.yml:   staging: +schema: silver   marts: +schema: gold
-- macros/generate_schema_name.sql на target prod отдаёт custom-схему
-- как есть -> SILVER / GOLD. На dev / ci -> <target.schema>_silver,
-- чтобы разработчик не писал в общий GOLD.
-- Проверка после dbt build --target prod:
SELECT table_schema, table_type, is_transient, count(*) AS objects
FROM ANALYTICS.INFORMATION_SCHEMA.TABLES
WHERE table_schema IN ('BRONZE', 'SILVER', 'GOLD')
GROUP BY 1, 2, 3
ORDER BY 1, 2;

-- ── 3. RBAC по слоям ────────────────────────────────────────
USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS LOADER;        -- Airbyte
CREATE ROLE IF NOT EXISTS TRANSFORMER;   -- dbt
CREATE ROLE IF NOT EXISTS REPORTER;      -- Lightdash, metrics_api

GRANT USAGE ON DATABASE ANALYTICS TO ROLE LOADER;
GRANT USAGE ON DATABASE ANALYTICS TO ROLE TRANSFORMER;
GRANT USAGE ON DATABASE ANALYTICS TO ROLE REPORTER;

-- LOADER: пишет только в Bronze и больше ничего не видит
GRANT USAGE, CREATE TABLE ON SCHEMA ANALYTICS.BRONZE TO ROLE LOADER;

-- TRANSFORMER: читает Bronze, владеет Silver и Gold
GRANT USAGE ON SCHEMA ANALYTICS.BRONZE TO ROLE TRANSFORMER;
GRANT SELECT ON ALL TABLES    IN SCHEMA ANALYTICS.BRONZE TO ROLE TRANSFORMER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS.BRONZE TO ROLE TRANSFORMER;
GRANT ALL ON SCHEMA ANALYTICS.SILVER TO ROLE TRANSFORMER;
GRANT ALL ON SCHEMA ANALYTICS.GOLD   TO ROLE TRANSFORMER;

-- REPORTER: только Gold. Здесь и видна польза слоёв как схем:
-- один FUTURE GRANT на схему, и любая новая витрина доступна BI
-- сразу после dbt build. Сырые таблицы с email и телефонами
-- в Bronze для BI недоступны физически, а не по договорённости.
GRANT USAGE ON SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON ALL TABLES    IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON ALL VIEWS     IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ANALYTICS.GOLD TO ROLE REPORTER;

-- Ловушка: вьюха в GOLD, которая читает BRONZE. Обычная вьюха
-- выполняется с правами владельца (TRANSFORMER), и REPORTER через неё
-- увидит Bronze. Контракт «Gold не читает Bronze» в dbt (step 2 урока)
-- закрывает именно эту дыру, а не только эстетику графа.

-- ── 4. Проверка изоляции ────────────────────────────────────
USE ROLE REPORTER;
SELECT count(*) FROM ANALYTICS.GOLD.FCT_ORDERS;          -- ок
SELECT count(*) FROM ANALYTICS.BRONZE.RAW_ORDERS;        -- ожидаем: insufficient privileges
SELECT count(*) FROM ANALYTICS.SILVER.STG_ORDERS;        -- ожидаем: insufficient privileges

-- ── 5. Миграция существующего проекта ───────────────────────
-- dbt не удаляет объект, когда модель меняет схему. После переезда
-- в старой схеме остаются таблицы-сироты, которые выглядят живыми.
-- Найти их: объекты старой схемы, которые не обновлялись после деплоя.
USE ROLE TRANSFORMER;
SELECT table_schema, table_name, last_altered
FROM ANALYTICS.INFORMATION_SCHEMA.TABLES
WHERE table_schema = 'PUBLIC'
  AND last_altered < DATEADD('day', -2, CURRENT_TIMESTAMP())
ORDER BY last_altered;
-- Удалять — только после того, как exposures и ACCESS_HISTORY
-- показали, что их никто не читает:
SELECT direct_objects_accessed, user_name, query_start_time
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
WHERE query_start_time > DATEADD('day', -14, CURRENT_TIMESTAMP())
  AND ARRAY_TO_STRING(direct_objects_accessed, ',') ILIKE '%PUBLIC.FCT_ORDERS%'
LIMIT 50;
"""


def step7_snowflake_sql():
    banner("STEP 7", "SQL под реальный Snowflake")
    path = SNOWFLAKE_DIR / "22_medallion_layers.sql"
    write_utf8(path, MEDALLION_SQL)
    return path


# ═══════════════════════════════════════════════════════════
#  STEP 8 — итог + собеседование
# ═══════════════════════════════════════════════════════════

def step8_summary(audit, violations, probe_caught, build, migration, orphans, rebuild):
    banner("STEP 8", "Итог + «На собеседовании»")
    n_orphans, n_bronze, foreign = orphans
    rows = [
        ("date", TODAY),
        ("layers_mixed_in_main_before", sum(1 for (s, l), c in audit.items()
                                            if s == "main" and l != "unknown" and c)),
        ("contract_violations", len(violations)),
        ("contract_probe_caught", f"{probe_caught}/1"),
        ("first_build", build[0]),
        ("first_build_sec", f"{build[1]:.1f}"),
        ("migration_same", migration["same"]),
        ("migration_volatile", migration["volatile"]),
        ("migration_changed", migration["changed"]),
        ("migration_new_models", migration["new"]),
        ("orphans_dropped", n_orphans),
        ("bronze_kept_in_main", n_bronze),
        ("foreign_kept_in_main", len(foreign)),
        ("rebuild_models", rebuild["models"]),
        ("rebuild_same", rebuild["same"]),
        ("rebuild_volatile", rebuild["volatile"]),
        ("rebuild_diff", rebuild["diff"]),
        ("rebuild_sec", f"{rebuild['sec']:.1f}"),
        ("snapshot_versions_total", rebuild["snap_total"]),
        ("snapshot_versions_closed", rebuild["snap_hist"]),
    ]
    for k, v in rows:
        print(f"  {k:<32} {v}")
    path = write_csv(REPORTS_DIR / "day101_104_summary.csv", ["metric", "value"], rows)

    print("""
  На собеседовании:

  «Что такое Medallion и как он ложится на dbt?»
  -> Три слоя с разными гарантиями. Bronze — данные 1:1 как пришли,
     неизменяемые, это зона загрузчика. Silver — очищено, типизировано,
     проверено тестами, одно зерно на сущность. Gold — собрано под бизнес-
     вопрос: факты, измерения, метрики. В dbt: sources, seeds и snapshots —
     Bronze, staging и intermediate — Silver, marts — Gold. Папки остаются
     dbt-слоями, а в Snowflake слой — это схема: на ней гранты и retention.

  «Куда в Medallion снапшоты?»
  -> В Bronze. Snapshot хранит историю, которой больше нет в источнике,
     и пересобрать его нельзя. Silver и Gold можно снести и пересобрать
     одной командой, snapshot — нет. Это и есть граница слоя: что
     восстанавливается, а что нет.

  «Зачем слои, если можно одну схему и хорошие имена?»
  -> Доступ и деньги. REPORTER получает SELECT на GOLD одним future
     grant'ом, и сырьё с PII физически недоступно BI. Silver делается
     TRANSIENT — без Fail-safe, потому что восстанавливается из Bronze.
     На одной схеме ни то, ни другое не выразить.

  «Как переехать на Medallion в живом проекте?»
  -> Сначала exposures и ACCESS_HISTORY: кто читает таблицы по имени
     схемы. Потом +schema в dbt_project.yml и generate_schema_name под
     prod. Сборка, сверка старой и новой копии по хешу строк. Отдельный
     шаг — сироты: dbt не удаляет старые таблицы, и потребитель, забытый
     в списке, тихо читает застывшие данные без единой ошибки.
""")
    return path


def main():
    t0 = time.perf_counter()
    if not DB_PATH.exists():
        raise SystemExit(f"Нет {DB_PATH} — сначала dbt build из прошлых уроков")

    audit = step1_audit_warehouse()
    nodes, disabled, violations, probe_caught = step2_contract()
    build = step3_build()
    migration = step4_migration_diff(nodes)
    orphans = step5_orphans(nodes, disabled)
    rebuild = step6_rebuild_from_bronze(nodes)
    sql_path = step7_snowflake_sql()
    summary_path = step8_summary(audit, violations, probe_caught, build,
                                 migration, orphans, rebuild)

    print("\n" + SEP)
    print(f"  ALL DONE  ({time.perf_counter() - t0:.0f} с)")
    print(SEP)
    print(f"""
Артефакты:
  {sql_path.relative_to(PROJECT_ROOT)}
  reports/day101_104_audit_before.csv
  reports/day101_104_contract.csv
  reports/day101_104_migration_diff.csv
  reports/day101_104_orphans.csv
  reports/day101_104_rebuild.csv
  {summary_path.relative_to(PROJECT_ROOT)}

Что осталось несделанным честно:
  Bronze не вынесен в отдельную схему: raw_* лежат в main, потому что
  туда пишут seeds, старые уроки и CI. Это миграция загрузчиков.
  Гранты по слоям и TRANSIENT Silver существуют только в скрипте 22 —
  Snowflake-аккаунта нет, скрипт не выполнялся.
  Старые уроки (lesson81_85.py и раньше) читают main.stg_* / main.mart_*
  по имени и после этого урока упадут на отсутствующей таблице.
  metrics_api смотрит в dev.duckdb, которого нет: баг старше этого
  урока, схема поправлена, путь к файлу — нет.

Next steps:
  1. Dagster: dg dev / dagster dev -> группы bronze / silver / gold,
     ключи ассетов прежние, история материализаций на месте
  2. Days 105-107 — dbt Mesh: разрезать проект на два и сослаться
     между ними. Слои из этого урока станут границей между проектами
  3. Концепт в базу: /ae-concept Medallion Architecture

Git:
  git add lesson101_104.py snowflake_setup/22_medallion_layers.sql reports/day101_104_* \\
          dbt_analytics/dbt_project.yml dbt_analytics/macros/generate_schema_name.sql \\
          dbt_analytics/models production_pipeline/assets_dbt.py metrics_api/main.py
  git commit -m "feat: Days 101-104 Medallion Architecture"
""")


if __name__ == "__main__":
    main()
