"""``python -m oilgas run`` in quick mode as a separate process: time, outputs and reproducibility (AC20, AC22)."""

from __future__ import annotations

import os
import shutil
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
    after = {p.name: p.read_bytes() for p in (root / "outputs/powerbi").glob("*.parquet")}
    assert after.pop("dim_pipeline_run.parquet") != before.pop("dim_pipeline_run.parquet")  # the run table shows the unchanged run (A6)
    assert after == before  # and nothing else is rewritten


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


def fingerprint(root: Path) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file where the full run keeps its versioned and generated state."""
    folders = [root / "outputs", root / "reports", root / "dashboard", root / "data" / "warehouse", root / "data" / "interim", root / "data" / "raw"]
    files = [f for folder in folders if folder.exists() for f in folder.rglob("*") if f.is_file()]
    files.append(root / "README.md")
    return {f.relative_to(root).as_posix(): (f.stat().st_size, f.stat().st_mtime_ns) for f in files}


def test_the_documented_quick_run_works_from_a_fresh_clone_and_writes_nothing_versioned() -> None:
    """B3: the commands of the README, as a separate process, leave every versioned output as it was."""
    sandbox = PROJECT / "data" / "quick"
    assert not sandbox.exists(), "data/quick is left over from another run"
    before = fingerprint(PROJECT)
    try:
        made = python_m("make-fixture", "data/quick/publication.csv", "--wells", "20", timeout=120)
        assert made.returncode == 0, made.stderr
        done = python_m("run", "--config", "config/pipeline.quick.toml")
        assert done.returncode == 0, done.stderr
        assert [line.split()[0] for line in done.stdout.splitlines() if line.strip()] == list(TASK_IDS)
        assert (sandbox / "outputs" / "powerbi" / "fact_forecast.parquet").exists() and (sandbox / "dashboard" / "powerbi-design.html").exists()
        assert fingerprint(PROJECT) == before
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_a_failed_task_shows_its_traceback_once_and_only_with_verbose(tmp_path: Path, fixture_csv: Path) -> None:
    """A4 as the person at the terminal sees it: the logging line never carries the trace, ``-v`` prints it once."""
    config = write_config(tmp_path, fixture_csv)
    quiet = python_m("task", "validate", "--config", str(config), "--run-key", "quiet", timeout=120)  # the download is missing: KeyError
    assert quiet.returncode == 1 and "failed: KeyError" in quiet.stderr and "Traceback" not in quiet.stderr
    loud = python_m("-v", "task", "validate", "--config", str(config), "--run-key", "loud", timeout=120)
    assert loud.returncode == 1 and loud.stderr.count("Traceback (most recent call last)") == 1


def test_a_quick_configuration_without_its_file_says_so_instead_of_crashing(tmp_path: Path) -> None:
    config = tmp_path / "local.toml"
    config.write_text(f'extends = "{(PROJECT / "config" / "pipeline.toml").as_posix()}"\n[source]\nmode = "local"\n', encoding="utf-8")
    done = python_m("run", "--config", str(config), timeout=60)
    assert done.returncode == 2 and "local_path" in done.stderr and "PermissionError" not in done.stderr


def test_the_module_answers_help_and_makes_a_fixture(tmp_path: Path) -> None:
    helped = python_m("--help", timeout=60)
    assert helped.returncode == 0 and "run" in helped.stdout and "make-fixture" in helped.stdout
    out = tmp_path / "f.csv"
    made = python_m("make-fixture", str(out), "--wells", "5", timeout=120)
    assert made.returncode == 0 and out.exists()
    assert python_m("task", "nonsense", timeout=60).returncode == 2
