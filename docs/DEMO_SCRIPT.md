# 2-Minute Pipeline Demo - Script

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
