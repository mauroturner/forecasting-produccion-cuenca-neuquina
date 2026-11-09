"""``airflow dags test`` in Docker in quick mode (AC19). Skipped unless the Docker engine is running.

Run it with ``pytest -m docker``. It builds the image of ``airflow/`` (several minutes the first time), starts
the database and the initialization service of the compose file, runs the DAG once on a synthetic publication
and stops the services. It writes only inside ``data/docker_test/`` and ``config/pipeline.docker-test.toml``
of the project, and removes them at the end.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.make_fixture import make_fixture

PROJECT = Path(__file__).resolve().parents[2]
AIRFLOW = PROJECT / "airflow"
WORK = PROJECT / "data" / "docker_test"
CONFIG = PROJECT / "config" / "pipeline.docker-test.toml"

pytestmark = pytest.mark.docker


def docker(*args: str, timeout: int = 1800, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "ENV_FILE_PATH": str(AIRFLOW / ".env.example"), "OILGAS_CONFIG": "/opt/oilgas/config/pipeline.docker-test.toml"}
    return subprocess.run(["docker", *args], cwd=AIRFLOW, env=env, capture_output=True, text=True, timeout=timeout, check=check, encoding="utf-8")


@pytest.fixture()
def engine():
    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("the Docker engine is not running")


def test_the_dag_runs_in_quick_mode_with_airflow_dags_test(engine) -> None:
    (WORK / "raw").mkdir(parents=True, exist_ok=True)
    make_fixture(WORK / "raw" / "publication.csv", n_wells=20, first=(2018, 1), last=(2024, 12), seed=0)
    base = "/opt/oilgas/data/docker_test"
    CONFIG.write_text(
        "\n".join([
            'extends = "pipeline.quick.toml"', "", "[source]", 'mode = "local"', f'local_path = "{base}/raw/publication.csv"', "",
            "[paths]", f'raw_dir = "{base}/raw"', f'interim_dir = "{base}/interim"', f'warehouse = "{base}/production.sqlite"',
            f'outputs_dir = "{base}/powerbi"', f'reports_dir = "{base}/reports"', f'dashboard_html = "{base}/powerbi-design.html"',
            f'readme = "{base}/README.md"', "",
        ]),
        encoding="utf-8",
    )
    try:
        docker("compose", "build")
        docker("compose", "up", "airflow-init")
        done = docker("compose", "--profile", "debug", "run", "--rm", "airflow-cli", "airflow", "dags", "test", "oilgas_monthly_production", check=False)
        assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
        assert (WORK / "powerbi" / "fact_forecast.parquet").exists() and (WORK / "powerbi-design.html").exists()
    finally:
        docker("compose", "down", check=False)
        CONFIG.unlink(missing_ok=True)
        shutil.rmtree(WORK, ignore_errors=True)
