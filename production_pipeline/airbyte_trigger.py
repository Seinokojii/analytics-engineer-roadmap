"""
production_pipeline/airbyte_trigger.py
Day 81-85: kak eto vyglyadit s realnym Airbyte (a ne simulyatsiey).

Airbyte OSS API v1: POST /api/v1/connections/sync -> job_id -> polling do success.
Sekrety tolko iz env: AIRBYTE_URL, AIRBYTE_CONNECTION_ID.

V Dagster etot vyzov stavitsya vnutr asseta vmesto sync_partition().
Alternativa - paket dagster-airbyte (pip install dagster-airbyte), on daet
gotovye assety iz Airbyte workspace. Zdes namerenno raw HTTP: menshe zavisimostey
i vidno, chto imenno proiskhodit.
"""

import os
import time

import requests

AIRBYTE_URL = os.environ.get("AIRBYTE_URL", "http://localhost:8000")
CONNECTION_ID = os.environ.get("AIRBYTE_CONNECTION_ID", "")

POLL_SECONDS = 15
TIMEOUT_MINUTES = 60


def trigger_sync(connection_id: str = CONNECTION_ID) -> dict:
    if not connection_id:
        raise RuntimeError("AIRBYTE_CONNECTION_ID is not set")

    resp = requests.post(
        f"{AIRBYTE_URL}/api/v1/connections/sync",
        json={"connectionId": connection_id},
        timeout=30,
    )
    resp.raise_for_status()
    job = resp.json()["job"]
    job_id = job["id"]
    print(f"Airbyte sync started: job {job_id}")

    deadline = time.time() + TIMEOUT_MINUTES * 60
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        status_resp = requests.post(
            f"{AIRBYTE_URL}/api/v1/jobs/get",
            json={"id": job_id},
            timeout=30,
        )
        status_resp.raise_for_status()
        status = status_resp.json()["job"]["status"]
        print(f"  job {job_id}: {status}")
        if status in ("succeeded", "failed", "cancelled"):
            if status != "succeeded":
                raise RuntimeError(f"Airbyte job {job_id} finished as {status}")
            return status_resp.json()["job"]

    raise TimeoutError(f"Airbyte job {job_id} did not finish in {TIMEOUT_MINUTES}m")


if __name__ == "__main__":
    trigger_sync()
