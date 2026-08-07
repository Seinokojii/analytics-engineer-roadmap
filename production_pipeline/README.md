# production_pipeline - Days 81-85

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
