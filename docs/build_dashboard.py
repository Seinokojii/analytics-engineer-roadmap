#!/usr/bin/env python3
"""Reads the dbt warehouse and Elementary tables, writes docs/data.json.

Everything on the dashboard is derived from this file, so the page can be
opened from disk or from GitHub Pages without a database. Row-level
subscriptions are included (500 rows) so filters recompute honestly in the
browser instead of switching between pre-rendered pictures.
"""
import datetime as dt
import json
import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "dbt_analytics" / "analytics.duckdb"
MANIFEST = ROOT / "dbt_analytics" / "target" / "manifest.json"
OUT = pathlib.Path(__file__).with_name("data.json")

SAAS_MODELS = ["stg_saas_users", "stg_subscriptions", "dim_subscribers", "fct_subscriptions",
               "mart_mrr_monthly", "mart_cohort_retention", "mart_ltv", "mart_rfm_segments"]
LAYER = {"stg_": "staging", "dim_": "core", "fct_": "core", "mart_": "mart"}
CHARTS = {"kpi": "fct_subscriptions", "mrr": "mart_mrr_monthly", "cohort": "mart_cohort_retention",
          "plan": "fct_subscriptions", "channel": "dim_subscribers", "ltv": "mart_ltv",
          "rfm": "mart_rfm_segments"}


def rows(con, sql):
    cur = con.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def iso(v):
    return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v


def clean(recs):
    return [{k: iso(v) for k, v in r.items()} for r in recs]


def lineage():
    m = json.loads(MANIFEST.read_text())
    nodes, edges = {}, set()

    def add_node(uid):
        if uid in nodes:
            return
        name = uid.split(".")[-1]
        if uid.startswith("source."):
            nodes[uid] = {"id": f"source.saas_raw.{name}", "name": name, "layer": "source"}
        else:
            layer = next((v for k, v in LAYER.items() if name.startswith(k)), "core")
            nodes[uid] = {"id": f"model.{name}", "name": name, "layer": layer}

    for uid, node in m["nodes"].items():
        if node["resource_type"] != "model" or node["name"] not in SAAS_MODELS:
            continue
        add_node(uid)
        for dep in node["depends_on"]["nodes"]:
            if dep.startswith("source.") or dep.split(".")[-1] in SAAS_MODELS:
                add_node(dep)
                edges.add((nodes[dep]["id"], nodes[uid]["id"]))
    # tests per model, for the lineage tooltips
    tests = {}
    for uid, node in m["nodes"].items():
        if node["resource_type"] != "test":
            continue
        for dep in node["depends_on"]["nodes"]:
            name = dep.split(".")[-1]
            if name in SAAS_MODELS:
                tests[name] = tests.get(name, 0) + 1
    for n in nodes.values():
        n["tests"] = tests.get(n["name"], 0)
    return {"nodes": list(nodes.values()), "edges": sorted(edges)}


def quality(con):
    inv = rows(con, """select invocation_id, run_started_at, command from main_elementary.dbt_invocations
                       where command = 'build' order by run_started_at desc limit 1""")[0]
    tests = rows(con, f"""select table_name as model, test_name as name, test_short_name as short,
                            column_name as "column", test_type as type, status
                     from main_elementary.elementary_test_results
                     where invocation_id = '{inv['invocation_id']}' order by 1, 2""")
    counts = {s: 0 for s in ("pass", "warn", "fail", "error")}
    for t in tests:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    hist = rows(con, """select i.run_started_at::date as date,
                          count(*) filter (where r.status = 'pass') as pass,
                          count(*) filter (where r.status <> 'pass') as fail
                        from main_elementary.elementary_test_results r
                        join main_elementary.dbt_invocations i using (invocation_id)
                        group by 1 order by 1""")
    return {"last_build": {"invocation_id": inv["invocation_id"], "started_at": iso(inv["run_started_at"]),
                           "command": inv["command"], **counts},
            "tests": tests, "history": clean(hist)}


def main():
    con = duckdb.connect(str(DB), read_only=True)
    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "dbt_analytics/analytics.duckdb",
        "subs": clean(rows(con, """select s.subscription_id as id, s.user_id as user, s.plan, s.mrr,
                                     s.start_date as start, s.end_date as "end",
                                     d.channel, d.country, d.signup_date as signup
                                   from fct_subscriptions s join dim_subscribers d using (user_id)
                                   order by s.subscription_id""")),
        "mrr_monthly": clean(rows(con, """select month, plan, active_subs as active, mrr,
                                            new_subs as new, churned_subs as churned
                                          from mart_mrr_monthly order by month, plan""")),
        "cohorts": clean(rows(con, """select cohort_month as cohort, month_num as k, cohort_size as size,
                                        active_subs as active, retention_pct as pct
                                      from mart_cohort_retention order by 1, 2""")),
        "ltv": clean(rows(con, "select * from mart_ltv order by avg_mrr desc")),
        "rfm": clean(rows(con, "select segment, count(*) as n from mart_rfm_segments group by 1 order by 2 desc")),
        "quality": quality(con),
        "lineage": lineage(),
        "charts": CHARTS,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {OUT.name}: {OUT.stat().st_size // 1024} KB, {len(data['subs'])} subs, "
          f"{len(data['lineage']['nodes'])} lineage nodes, last build {data['quality']['last_build']['started_at']} "
          f"pass={data['quality']['last_build']['pass']}")


if __name__ == "__main__":
    main()
