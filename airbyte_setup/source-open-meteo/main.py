"""Точка входа коннектора: python main.py spec | check | discover | read."""

import sys

from airbyte_cdk.entrypoint import launch

from source_open_meteo import SourceOpenMeteo

if __name__ == "__main__":
    launch(SourceOpenMeteo(), sys.argv[1:])
