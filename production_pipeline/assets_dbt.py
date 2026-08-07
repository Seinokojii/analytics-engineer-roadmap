"""
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
