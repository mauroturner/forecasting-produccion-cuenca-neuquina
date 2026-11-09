"""The pipeline end to end in quick mode: tasks, state, manifest, unchanged and late runs, rejection without damage (AC04, AC19, AC20)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from oilgas import pipeline
from oilgas.config import load_config
from oilgas.dashboard.semantic_model import MODEL
from oilgas.export import verify_star_schema
from oilgas.ingest import read_manifest
from oilgas.pipeline import TASK_IDS, TASKS, make_run_key, run_all, run_task
from oilgas.validate import ValidationError, read_report
from tests.fixtures.http_server import PublicationServer
from tests.fixtures.modeling import write_config

NOW = datetime(2025, 1, 20, 9, tzinfo=UTC)
PLANNED = ["check_publication", "download", "validate", "load", "backtest", "forecast", "export", "render_dashboard", "report"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    """The hash of the warehouse, every exported Parquet and the HTML design."""
    files = [root / "data/warehouse/production.sqlite", root / "dashboard/powerbi-design.html", *sorted((root / "outputs/powerbi").glob("*.parquet"))]
    return {f.relative_to(root).as_posix(): sha(f) for f in files}


def sqlite_rows(root: Path, sql: str, *args) -> list[tuple]:
    with sqlite3.connect(root / "data/warehouse/production.sqlite") as conn:
        return conn.execute(sql, args).fetchall()


@pytest.fixture()
def copy_of_run(tmp_path: Path, quick_run) -> tuple[Path, Path]:
    """A private copy of the finished quick run and a config file that points at it (same local publication)."""
    root, config, _ = quick_run
    copy = tmp_path / "copy"
    shutil.copytree(root, copy)
    csv = Path(load_config(config).source.local_path)
    return copy, write_config(copy, csv)


# --- the task list -----------------------------------------------------------------------------------------------


def test_the_tasks_are_the_nine_of_the_plan_in_order_with_their_limits() -> None:
    assert list(TASK_IDS) == PLANNED == [t.task_id for t in TASKS]
    limits = {t.task_id: (t.retries, t.retry_delay_min, t.timeout_min) for t in TASKS}
    assert limits == {
        "check_publication": (3, 10, 5), "download": (3, 15, 30), "validate": (0, 0, 15), "load": (1, 5, 20), "backtest": (1, 10, 120),
        "forecast": (1, 10, 45), "export": (1, 5, 10), "render_dashboard": (1, 5, 10), "report": (1, 5, 5),
    }
    assert [t.task_id for t in TASKS if t.short_circuit] == ["check_publication"]
    assert all(callable(t.func) for t in TASKS)


def test_a_run_key_comes_from_an_airflow_run_id_or_from_a_utc_time() -> None:
    assert make_run_key("scheduled__2026-11-09T09:00:00+00:00") == "scheduled__2026-11-09T09_00_00_00_00"
    assert make_run_key(datetime(2026, 11, 9, 9, 30, 5, tzinfo=UTC)) == "20261109T093005Z"
    assert make_run_key(datetime(2026, 11, 9, 6, 30, 5, tzinfo=UTC).astimezone()) == "20261109T063005Z"
    with pytest.raises(ValueError, match="empty"):
        make_run_key("///")


# --- one complete run -----------------------------------------------------------------------------------------------


def test_a_run_goes_through_the_nine_tasks_in_order(quick_run) -> None:
    _, _, outcome = quick_run
    assert [item["task"] for item in outcome] == PLANNED
    assert outcome[0]["result"]["changed"] is True and all("seconds" in item["result"] for item in outcome)


def test_every_output_of_the_pipeline_exists_and_the_star_schema_keeps_its_contract(quick_run) -> None:
    root, config, _ = quick_run
    cfg = load_config(config)
    assert (root / "data/warehouse/production.sqlite").exists() and (root / "data/interim/validated_subset.parquet").exists()
    for name in ("point_forecasts", "ml_forecasts", "errors"):
        assert (root / f"data/interim/backtest/{name}.parquet").exists()
    assert sorted(p.name for p in (root / "outputs/powerbi").glob("*.parquet")) == sorted(f"{t.name}.parquet" for t in MODEL.tables)
    assert verify_star_schema(cfg.paths.outputs_dir, MODEL) == []
    html = (root / "dashboard/powerbi-design.html").read_text(encoding="utf-8")
    assert "CC BY 4.0" in html and html.count('<div class="canvas"') == 5
    for name in ("backtest_summary.json", "backtest_summary.md"):
        assert (root / "reports" / name).exists()
    assert (root / "reports/validation/latest.json").exists() and (root / "reports/validation/latest.md").exists()
    leftovers = [p for p in root.rglob("*") if p.suffix == ".tmp" or p.name.endswith(".part")]
    assert leftovers == []


def test_the_state_file_keeps_what_every_task_produced(quick_run) -> None:
    root, _, outcome = quick_run
    [state_file] = list((root / "data/interim/runs").glob("*.json"))
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["status"] == "ok" and state["started_at"].startswith("2025-01-20T09:00:00")
    assert list(state["tasks"]) == PLANNED
    assert state["tasks"]["load"]["rows"] == outcome[3]["result"]["rows"] > 0
    assert state["tasks"]["validate"]["last_period_key"] == 202412 and state["run_key"] == state_file.stem


def test_the_manifest_marks_the_publication_loaded_only_at_the_end(quick_run) -> None:
    root, config, _ = quick_run
    [entry] = read_manifest(root / "data/raw/manifest.json")
    csv = Path(load_config(config).source.local_path)
    assert entry.status == "loaded" and entry.sha256 == sha(csv) and entry.size == csv.stat().st_size


def test_the_run_record_the_validation_results_and_the_period_are_in_the_warehouse(quick_run) -> None:
    root, _, outcome = quick_run
    [row] = sqlite_rows(root, "SELECT run_key, status, source_sha256, last_period_key, rows_subset, wells_subset, finished_at FROM pipeline_runs")
    assert row[1] == "ok" and row[3] == 202412 and row[4] == outcome[3]["result"]["rows"] and row[6]
    assert sqlite_rows(root, "SELECT COUNT(*) FROM validation_results WHERE run_key = ?", row[0]) == [(23,)]
    assert sqlite_rows(root, "SELECT COUNT(*) FROM raw_monthly_production")[0][0] == row[4]


def test_the_exported_run_table_says_ok_and_has_the_validation_rules(quick_run) -> None:
    root, _, _ = quick_run
    runs = pd.read_parquet(root / "outputs/powerbi/dim_pipeline_run.parquet")
    assert runs["status"].tolist() == ["ok"] and runs["last_period_key"].tolist() == [202412]
    assert len(pd.read_parquet(root / "outputs/powerbi/fact_validation.parquet")) == 23


# --- an unchanged or late publication -------------------------------------------------------------------------------------


def test_an_unchanged_publication_ends_the_run_after_the_check_and_touches_no_output(copy_of_run) -> None:
    root, config = copy_of_run
    before = snapshot(root)
    [only] = run_all(load_config(config), now=datetime(2025, 1, 25, 9, tzinfo=UTC))
    assert only["task"] == "check_publication" and only["result"]["changed"] is False
    assert only["result"]["status"] == "unchanged" and only["result"]["late"] is False
    assert only["result"]["days_since_last_period"] == 25  # from 2024-12-31
    after = snapshot(root)
    after_warehouse = after.pop("data/warehouse/production.sqlite")
    before.pop("data/warehouse/production.sqlite")
    assert after == before  # no Parquet and no HTML changed
    assert after_warehouse
    statuses = dict(sqlite_rows(root, "SELECT status, COUNT(*) FROM pipeline_runs GROUP BY status"))
    assert statuses == {"ok": 1, "unchanged": 1}
    assert sqlite_rows(root, "SELECT COUNT(*) FROM raw_monthly_production")[0][0] > 0


def test_an_unchanged_publication_whose_last_month_is_too_old_is_recorded_as_late(copy_of_run) -> None:
    root, config = copy_of_run
    [only] = run_all(load_config(config), now=datetime(2025, 6, 30, 9, tzinfo=UTC))
    assert only["result"]["status"] == "late" and only["result"]["late"] is True and only["result"]["days_since_last_period"] == 181
    [(status, message)] = sqlite_rows(root, "SELECT status, message FROM pipeline_runs WHERE status = 'late'")
    assert status == "late" and "55" in message and "181" in message
    fifty_five = run_all(load_config(config), now=datetime(2025, 2, 24, 9, tzinfo=UTC))  # 55 days after 2024-12-31: still on time
    assert fifty_five[0]["result"]["status"] == "unchanged"
    sixty = run_all(load_config(config), now=datetime(2025, 2, 25, 9, tzinfo=UTC))  # 56 days
    assert sixty[0]["result"]["status"] == "late"


def test_a_changed_publication_runs_again(copy_of_run, tmp_path: Path) -> None:
    root, config = copy_of_run
    csv = Path(load_config(config).source.local_path)
    newer = tmp_path / "newer.csv"
    newer.write_bytes(csv.read_bytes() + b"\n")  # another size: the publication changed
    outcome = run_all(load_config(write_config(root, newer)), now=NOW, only=["check_publication"])
    assert outcome[0]["result"]["changed"] is True and "status" not in outcome[0]["result"]  # a changed publication goes on


# --- a rejected publication (RF04, AC04) -------------------------------------------------------------------------------------


def test_a_rejected_publication_leaves_the_warehouse_the_parquet_and_the_html_byte_for_byte(copy_of_run, malformed, tmp_path: Path) -> None:
    root, _ = copy_of_run
    bad = malformed("non_numeric_well_id")
    config = write_config(root, bad)
    before = snapshot(root)
    with pytest.raises(ValidationError) as info:
        run_all(load_config(config), now=datetime(2025, 2, 20, 9, tzinfo=UTC))
    assert snapshot(root) == before  # the SHA-256 of SQLite and of every Parquet is the same as before (AC04)
    assert "V03" in str(info.value) and info.value.report.blocking_failed
    manifest = read_manifest(root / "data/raw/manifest.json")
    assert [e.status for e in manifest] == ["loaded", "rejected"]
    quarantined = list((root / "data/raw/quarantine").glob("*.csv"))
    assert len(quarantined) == 1 and sha(quarantined[0]) == sha(bad) and bad.exists()  # copied: the file was not ours to move
    latest = read_report(root / "reports/validation/latest.json")
    assert latest.blocking_failed and any(r.rule_id == "V03" and not r.passed for r in latest.results)
    state_file = sorted((root / "data/interim/runs").glob("*.json"), key=lambda p: p.stat().st_mtime)[-1]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["status"] == "rejected" and state["tasks"]["validate"]["rules"] == ["V03"]
    assert list(state["tasks"]) == ["check_publication", "download", "validate"]  # nothing after the rejection ran
    assert sqlite_rows(root, "SELECT COUNT(*) FROM pipeline_runs") == [(1,)]  # no record of the rejected run in the warehouse


def test_a_rejected_file_inside_the_raw_folder_is_moved_to_quarantine(copy_of_run, malformed) -> None:
    root, _ = copy_of_run
    inside = root / "data/raw/new.csv"
    shutil.copy(malformed("non_numeric_well_id"), inside)
    digest = sha(inside)
    with pytest.raises(ValidationError):
        run_all(load_config(write_config(root, inside)), now=datetime(2025, 2, 20, 9, tzinfo=UTC))
    assert not inside.exists()
    assert [sha(p) for p in (root / "data/raw/quarantine").glob("*.csv")] == [digest]


# --- failures -------------------------------------------------------------------------------------------------------------


def test_a_failing_task_marks_the_run_failed_and_keeps_the_error(copy_of_run, monkeypatch) -> None:
    root, config = copy_of_run
    cfg = load_config(config)
    [state_file] = list((root / "data/interim/runs").glob("*.json"))
    run_key = state_file.stem

    def boom(ctx):
        raise RuntimeError("the model exploded")

    monkeypatch.setattr(pipeline, "run_production_forecast", boom)
    with pytest.raises(RuntimeError, match="exploded"):
        run_task("forecast", run_key, cfg)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["status"] == "failed" and "the model exploded" in state["tasks"]["forecast"]["error"]
    [(status, message)] = sqlite_rows(root, "SELECT status, message FROM pipeline_runs WHERE run_key = ?", run_key)
    assert status == "failed" and "forecast" in message and "exploded" in message


def test_a_failure_before_the_load_leaves_no_record_in_the_warehouse(tmp_path: Path, fixture_csv: Path, monkeypatch) -> None:
    config = write_config(tmp_path, fixture_csv)

    def boom(*args, **kwargs):
        raise OSError("the disk is full")

    monkeypatch.setattr(pipeline, "adopt_local_file", boom)
    with pytest.raises(OSError, match="disk"):
        run_all(load_config(config), now=NOW)
    [state_file] = list((tmp_path / "data/interim/runs").glob("*.json"))
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["status"] == "failed" and state["tasks"]["download"]["status"] == "failed"
    assert sqlite_rows(tmp_path, "SELECT COUNT(*) FROM sqlite_master WHERE name = 'pipeline_runs'") == [(0,)]  # nothing was written to the warehouse


# --- running tasks one by one, as Airflow does -----------------------------------------------------------------------------------


def test_tasks_of_one_run_share_their_state_through_the_run_id(tmp_path: Path, fixture_csv: Path) -> None:
    cfg = load_config(write_config(tmp_path, fixture_csv))
    run_id = "scheduled__2025-01-20T09:00:00+00:00"
    first = run_task("check_publication", run_id, cfg, now=NOW)
    run_task("download", run_id, cfg, now=datetime(2025, 1, 21, tzinfo=UTC))  # a later call does not move the start of the run
    done = run_task("validate", run_id, cfg)
    key = make_run_key(run_id)
    state = json.loads((tmp_path / "data/interim/runs" / f"{key}.json").read_text(encoding="utf-8"))
    assert state["started_at"].startswith("2025-01-20T09:00:00") and list(state["tasks"]) == ["check_publication", "download", "validate"]
    assert first["changed"] is True and done["rows_subset"] > 0 and (tmp_path / "data/interim/validated_subset.parquet").exists()
    assert done["last_period_key"] == 202412 and key == "scheduled__2025-01-20T09_00_00_00_00"


def test_only_and_from_select_tasks_of_a_run(tmp_path: Path, fixture_csv: Path) -> None:
    cfg = load_config(write_config(tmp_path, fixture_csv))
    first = run_all(cfg, only=["check_publication", "download"], run_key="r-sel", now=NOW)
    assert [i["task"] for i in first] == ["check_publication", "download"]
    rest = run_all(cfg, start="validate", only=["validate", "load"], run_key="r-sel")
    assert [i["task"] for i in rest] == ["validate", "load"]
    assert rest[1]["result"]["rows"] > 0
    with pytest.raises(ValueError, match="nonsense"):
        run_all(cfg, only=["nonsense"])
    with pytest.raises(ValueError, match="nonsense"):
        run_task("nonsense")


def test_a_task_that_needs_an_earlier_one_says_so(tmp_path: Path, fixture_csv: Path) -> None:
    cfg = load_config(write_config(tmp_path, fixture_csv))
    with pytest.raises(KeyError):
        run_task("download", "r-alone", cfg)  # nothing was checked: there is no publication metadata in the state


# --- http source: download or adopt ----------------------------------------------------------------------------------------------


def http_config(root: Path, server: PublicationServer) -> Path:
    config = write_config(root, root / "unused.csv")
    text = config.read_text(encoding="utf-8").replace('mode = "local"', 'mode = "http"')
    text = text.replace("[source]", f'[source]\nurl = "{server.url}"\nchunk_bytes = 65536\ntimeout_s = 10', 1)
    config.write_text(text, encoding="utf-8")
    return config


def test_the_publication_is_downloaded_whole_and_listed_in_the_manifest(tmp_path: Path, fixture_csv: Path) -> None:
    body = fixture_csv.read_bytes()
    with PublicationServer(body=body) as server:
        cfg = load_config(http_config(tmp_path, server))
        outcome = run_all(cfg, only=["check_publication", "download"], now=NOW)
        assert outcome[1]["result"]["how"] == "download" and outcome[1]["result"]["size"] == len(body)
        assert server.methods() == ["HEAD", "GET"]
    [entry] = read_manifest(tmp_path / "data/raw/manifest.json")
    assert entry.status == "downloaded" and entry.sha256 == hashlib.sha256(body).hexdigest()
    assert Path(entry.local_path).read_bytes() == body and entry.etag == '"v1"'


def test_an_adopted_file_is_not_downloaded_again(tmp_path: Path, fixture_csv: Path) -> None:
    body = fixture_csv.read_bytes()
    with PublicationServer(body=body) as server:
        cfg = load_config(http_config(tmp_path, server))
        outcome = run_all(cfg, adopt=fixture_csv, only=["check_publication", "download"], now=NOW)
        assert outcome[1]["result"]["how"] == "adopt" and server.methods() == ["HEAD"]  # no GET
    assert read_manifest(tmp_path / "data/raw/manifest.json")[0].sha256 == hashlib.sha256(body).hexdigest()


def test_a_tasks_own_stage_times_are_kept_next_to_its_total(tmp_path: Path) -> None:
    """The backtest and the forecast report their stages; the run state must keep them, not overwrite them with the total."""
    cfg = load_config()
    ctx = pipeline.RunContext(cfg, "k", NOW, tmp_path / "state.json")
    staged = pipeline.TaskSpec("staged", lambda _: {"seconds": {"ml": 2.5, "total": 3.0}, "rows": 1}, 0, 0, 1)
    plain = pipeline.TaskSpec("plain", lambda _: {"rows": 2}, 0, 0, 1)
    result = pipeline._run_spec(staged, ctx)
    assert result["stage_seconds"] == {"ml": 2.5, "total": 3.0} and isinstance(result["seconds"], float)
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"]["staged"]["stage_seconds"]["ml"] == 2.5
    assert "stage_seconds" not in pipeline._run_spec(plain, ctx) and plain.func(ctx) == {"rows": 2}
