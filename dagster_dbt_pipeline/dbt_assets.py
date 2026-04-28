# dagster_dbt_pipeline/dbt_assets.py
# Day 66-67: load_assets_from_dbt_project
# Vse dbt modeli -> Dagster assets avtomaticheski
# [[Dagster]] [[dbt]] [[DuckDB]]

from pathlib import Path
from dagster import AssetExecutionContext
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

# Путь к нашему dbt проекту
DBT_PROJECT_DIR  = Path(__file__).parent.parent / "dbt_analytics"
DBT_PROFILES_DIR = Path.home() / ".dbt"   # ~/.dbt/profiles.yml

# DbtProject — описывает путь к dbt проекту
dbt_project = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROFILES_DIR,
)
dbt_project.prepare_if_dev()


# @dbt_assets — все dbt модели как Dagster assets
# Dagster chitaet manifest.json i stroit lineage avtomaticheski
@dbt_assets(manifest=dbt_project.manifest_path)
def analytics_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["run"], context=context).stream()