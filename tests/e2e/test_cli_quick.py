"""``python -m oilgas run`` in quick mode as a separate process: time, outputs and reproducibility (AC20, AC22)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from oilgas.dashboard.semantic_model import MODEL
from oilgas.export import verify_star_schema
from oilgas.pipeline import TASK_IDS
from tests.fixtures.modeling import write_config

PROJECT = Path(__file__).resolve().parents[2]
RUN_COLUMNS = {"run_key", "started_at", "finished_at", "message"}  # what depends on the run, not on the data


def python_m(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(PROJECT / "src"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "oilgas", *args], cwd=PROJECT, env=env, capture_output=True, text=True, timeout=timeout, encoding="utf-8")


@pytest.fixture(scope="module")
def cli_run(tmp_path_factory, fixture_csv: Path):
    root = tmp_path_factory.mktemp("cli_run")
    config = write_config(root, fixture_csv)
    started = time.perf_counter()
    done = python_m("run", "--config", str(config))
    return root, config, done, time.perf_counter() - started


def test_the_whole_flow_runs_from_the_command_line_in_under_three_minutes(cli_run) -> None:
    root, _, done, seconds = cli_run
    assert done.returncode == 0, done.stderr
    assert seconds <= 180  # AC20
    lines = [line.split()[0] for line in done.stdout.splitlines() if line.strip()]
    assert lines == list(TASK_IDS)
    assert (root / "dashboard/powerbi-design.html").stat().st_size < 2 * 1024 * 1024
    assert verify_star_schema(root / "outputs/powerbi", MODEL) == []
    assert (root / "reports/backtest_summary.md").exists()


def test_a_second_run_on_the_same_publication_does_nothing(cli_run) -> None:
    root, config, _, _ = cli_run
    before = {p.name: p.read_bytes() for p in (root / "outputs/powerbi").glob("*.parquet")}
    again = python_m("run", "--config", str(config))
    assert again.returncode == 0 and "unchanged:" in again.stdout and again.stdout.count("\n") == 2
    assert {p.name: p.read_bytes() for p in (root / "outputs/powerbi").glob("*.parquet")} == before


def test_two_runs_on_the_same_input_give_the_same_tables_apart_from_the_run_columns(cli_run, quick_run) -> None:
    """The in-process run of the shared fixture and this separate process started from the same file (AC22)."""
    root_a, _, _ = quick_run
    root_b = cli_run[0]
    for table in MODEL.tables:
        if table.name == "dim_pipeline_run":
            continue  # every column of it describes the run
        a = pd.read_parquet(root_a / "outputs/powerbi" / f"{table.name}.parquet")
        b = pd.read_parquet(root_b / "outputs/powerbi" / f"{table.name}.parquet")
        keep = [c for c in a.columns if c not in RUN_COLUMNS]
        pd.testing.assert_frame_equal(a[keep], b[keep], check_exact=True, obj=table.name)


def test_the_module_answers_help_and_makes_a_fixture(tmp_path: Path) -> None:
    helped = python_m("--help", timeout=60)
    assert helped.returncode == 0 and "run" in helped.stdout and "make-fixture" in helped.stdout
    out = tmp_path / "f.csv"
    made = python_m("make-fixture", str(out), "--wells", "5", timeout=120)
    assert made.returncode == 0 and out.exists()
    assert python_m("task", "nonsense", timeout=60).returncode == 2
