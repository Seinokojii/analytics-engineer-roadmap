import json, subprocess, sys, pathlib
from datetime import date

HERE = pathlib.Path(__file__).parent


def month_end_ordinal(m):
    y, mo = int(m[:4]), int(m[5:7])
    nxt = date(y + (mo == 12), mo % 12 + 1, 1)
    return nxt.toordinal() - 1


def test_build_writes_consistent_json():
    subprocess.run([sys.executable, str(HERE / "build_dashboard.py")], check=True)
    d = json.loads((HERE / "data.json").read_text())
    assert len(d["subs"]) == 500
    # Month-end MRR recomputed from rows must equal the dbt mart.
    mart = {}
    for r in d["mrr_monthly"]:
        mart[r["month"]] = mart.get(r["month"], 0) + r["mrr"]
    assert len(mart) == 21
    for m, mart_mrr in mart.items():
        me = month_end_ordinal(m)
        rows = sum(s["mrr"] for s in d["subs"]
                   if date.fromisoformat(s["start"]).toordinal() <= me
                   and (s["end"] is None or date.fromisoformat(s["end"]).toordinal() > me))
        assert abs(rows - mart_mrr) < 0.01, (m, rows, mart_mrr)
    assert {c["k"] for c in d["cohorts"]} == set(range(13))
    assert d["quality"]["last_build"]["error"] == 0
    assert d["quality"]["last_build"]["pass"] > 0
    names = {n["name"] for n in d["lineage"]["nodes"]}
    assert {"raw_subscriptions", "stg_subscriptions", "fct_subscriptions",
            "mart_cohort_retention", "mart_mrr_monthly"} <= names
    ids = {n["id"] for n in d["lineage"]["nodes"]}
    assert all(len(e) == 2 and e[0] in ids and e[1] in ids for e in d["lineage"]["edges"])
    assert set(d["charts"].values()) <= names
