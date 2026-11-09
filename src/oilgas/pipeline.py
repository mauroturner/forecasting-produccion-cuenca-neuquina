"""The pipeline as one tuple of tasks that the CLI and the Airflow DAG both walk (RF19, plan section 15).

Every task is a function ``fn(ctx) -> dict`` with no dependency on Airflow. Tasks pass state to each other
through files and tables, never through the orchestrator: each run has ``data/interim/runs/<run_key>.json``
with what every task produced. The run record in SQLite (``pipeline_runs``) is written only when the run
has something to say about the warehouse: an unchanged or late publication, or a load. A rejected or failed
run before the load leaves the SQLite file and the exported files byte for byte as they were (RF04, AC04);
its record is in the state file and in ``reports/validation/history``.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd

from oilgas.backtest import run_backtest
from oilgas.config import PipelineConfig, load_config
from oilgas.dashboard.render import render_design
from oilgas.dashboard.semantic_model import MODEL
from oilgas.export import export_star_schema, oversized_files, verify_star_schema
from oilgas.files import atomic_path, write_atomic
from oilgas.forecast import run_production_forecast
from oilgas.ingest import (
    ManifestEntry,
    RemoteMeta,
    adopt_local_file,
    append_manifest,
    download_file,
    head_remote,
    is_changed,
    last_loaded,
    local_meta,
    mark_manifest,
    quarantine,
    read_manifest,
)
from oilgas.reporting import evaluate_criteria, read_summary, write_summary
from oilgas.validate import ValidationError, read_report, validate_file, write_report
from oilgas.warehouse import (
    apply_schema,
    connect,
    load_validated_subset,
    previous_load,
    record_run,
    record_validation_results,
)

logger = logging.getLogger(__name__)

ATTRIBUTION = (
    'Fuente de datos: Secretaría de Energía de la Nación, "Producción de petróleo y gas por pozo (Capítulo IV)", datos.gob.ar, '
    "licencia CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Modificaciones: se filtró por cuenca y tipo de recurso, "
    "se validaron registros, se estimaron curvas de declinación de Arps y se calcularon proyecciones y bandas P10/P50/P90."
)
RUN_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ExportError(RuntimeError):
    """The exported files do not keep the contract of the star schema."""


@dataclass(frozen=True)
class RunContext:
    cfg: PipelineConfig
    run_key: str
    started_at: datetime
    state_path: Path


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    func: Callable[[RunContext], dict]
    retries: int
    retry_delay_min: int
    timeout_min: int
    short_circuit: bool = False


# --- run key and state ------------------------------------------------------------------------------------------


def make_run_key(source: str | datetime) -> str:
    """The key of a run: from an Airflow ``run_id`` (made safe for file names) or from a UTC time."""
    if isinstance(source, datetime):
        return source.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    key = RUN_KEY_UNSAFE.sub("_", str(source)).strip("_")
    if not key:
        raise ValueError("a run key cannot be empty")
    return key


def _state_path(cfg: PipelineConfig, run_key: str) -> Path:
    return Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json"


def _read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_state(path: Path, state: dict) -> None:
    write_atomic(path, json.dumps(state, indent=2, ensure_ascii=False, default=str) + "\n")


def _context(cfg: PipelineConfig, run_id: str | None, now: datetime | None, adopt: Path | None = None) -> RunContext:
    """The context of a run; ``started_at`` and the adopted file are fixed by the first task and kept in the state file."""
    when = (now or datetime.now(UTC)).astimezone(UTC)
    run_key = make_run_key(run_id if run_id is not None else when)
    path = _state_path(cfg, run_key)
    state = _read_state(path)
    if not state:
        state = {"run_key": run_key, "started_at": when.isoformat(timespec="seconds"), "adopt": str(adopt) if adopt else None, "status": "running", "tasks": {}}
        _write_state(path, state)
    elif adopt is not None and not state.get("adopt"):
        state["adopt"] = str(adopt)
        _write_state(path, state)
    return RunContext(cfg, run_key, datetime.fromisoformat(state["started_at"]), path)


def _task_result(ctx: RunContext, task_id: str) -> dict:
    return _read_state(ctx.state_path).get("tasks", {}).get(task_id, {})


def _save_task(ctx: RunContext, task_id: str, result: dict, status: str | None = None) -> None:
    state = _read_state(ctx.state_path)
    state.setdefault("tasks", {})[task_id] = result
    if status:
        state["status"] = status
    _write_state(ctx.state_path, state)


def _record(ctx: RunContext, **fields) -> None:
    """Write fields of this run to ``pipeline_runs`` (the row is created on the first call)."""
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        record_run(conn, {"run_key": ctx.run_key, **fields})
    finally:
        conn.close()


def _has_record(ctx: RunContext) -> bool:
    path = Path(ctx.cfg.paths.warehouse)
    if not path.exists():
        return False
    conn = connect(path)
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'pipeline_runs'").fetchone()
        return bool(exists and conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone())
    finally:
        conn.close()


def _now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _manifest_path(cfg: PipelineConfig) -> Path:
    return Path(cfg.paths.raw_dir) / "manifest.json"


# --- tasks ----------------------------------------------------------------------------------------------------------


def _remote_meta(cfg: PipelineConfig) -> RemoteMeta:
    if cfg.source.mode == "local":
        return local_meta(Path(cfg.source.local_path))
    return head_remote(cfg.source.url, cfg.source.timeout_s)


def _period_end(period_key: int) -> date:
    year, month = period_key // 100, period_key % 100
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def check_publication(ctx: RunContext) -> dict:
    """``HEAD`` the publication and compare it with the last load; an unchanged one ends the run (RF01, RF20)."""
    cfg = ctx.cfg
    remote = _remote_meta(cfg)
    last = last_loaded(read_manifest(_manifest_path(cfg)))
    changed = is_changed(remote, last)
    result: dict = {"changed": changed, "remote": asdict(remote), "late": False, "days_since_last_period": None}
    conn = connect(cfg.paths.warehouse)
    try:
        previous = previous_load(conn)
    finally:
        conn.close()
    if previous is not None:
        result["days_since_last_period"] = (ctx.started_at.date() - _period_end(previous.last_period_key)).days
    if not changed:
        late = result["days_since_last_period"] is not None and result["days_since_last_period"] > cfg.validation.freshness_max_days
        status = "late" if late else "unchanged"
        result["late"], result["status"] = late, status
        message = (
            f"the publication did not change; the last loaded month is {result['days_since_last_period']} days old"
            + (f" (more than {cfg.validation.freshness_max_days}): late" if late else "")
        )
        _record(ctx, started_at=ctx.started_at.isoformat(timespec="seconds"), finished_at=_now_text(), status=status,
                source_url=remote.url, source_etag=remote.etag, source_last_modified=remote.last_modified, source_size=remote.size, message=message)
        logger.info("run %s: %s", ctx.run_key, message)
    return result


def download(ctx: RunContext) -> dict:
    """Download the publication whole (or adopt a file that is already there) and add it to the manifest (RF02)."""
    cfg = ctx.cfg
    remote = RemoteMeta(**_task_result(ctx, "check_publication")["remote"])
    state = _read_state(ctx.state_path)
    if cfg.source.mode == "local":
        path, how = Path(cfg.source.local_path), "local"
    elif state.get("adopt"):
        path, how = Path(state["adopt"]), "adopt"
    else:
        name = Path(unquote(urlparse(remote.url).path)).name or "publication.csv"
        path, how = Path(cfg.paths.raw_dir) / name, "download"
    if how == "download":
        path, sha = download_file(remote.url, path, remote.size, cfg.source.chunk_bytes, cfg.source.timeout_s)
        entry = ManifestEntry(
            url=remote.url, etag=remote.etag, last_modified=remote.last_modified, size=path.stat().st_size, sha256=sha,
            local_path=path.as_posix(), downloaded_at=_now_text(), status="downloaded", run_key=ctx.run_key,
        )
    else:
        entry = adopt_local_file(path, remote, ctx.run_key)
    append_manifest(_manifest_path(cfg), entry)
    return {"path": str(path), "sha256": entry.sha256, "size": entry.size, "how": how}


def _quarantine(path: Path, cfg: PipelineConfig, sha256: str) -> Path:
    """Move a rejected file out of ``data/raw``; a file that is not ours (adopted or local) is copied, never moved."""
    target_dir = Path(cfg.paths.raw_dir) / "quarantine"
    raw = Path(cfg.paths.raw_dir).resolve()
    if raw in Path(path).resolve().parents:
        return quarantine(path, target_dir, sha256)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{Path(path).stem}.{sha256[:12]}{Path(path).suffix}"
    shutil.copy2(path, target)
    return target


def validate(ctx: RunContext) -> dict:
    """Validate the file against the contract; a blocking rule quarantines it and ends the run as rejected (RF03, RF04)."""
    cfg = ctx.cfg
    csv = Path(_task_result(ctx, "download")["path"])
    conn = connect(cfg.paths.warehouse)
    try:
        previous = previous_load(conn)
    finally:
        conn.close()
    report, frame = validate_file(csv, cfg, previous, ctx.run_key, ctx.started_at.date())
    write_report(report, Path(cfg.paths.reports_dir) / "validation")
    if report.blocking_failed:
        moved = _quarantine(csv, cfg, report.source_sha256)
        mark_manifest(_manifest_path(cfg), ctx.run_key, "rejected")
        state = _read_state(ctx.state_path)
        state["status"] = "rejected"
        state["tasks"]["validate"] = {"status": "rejected", "quarantine": str(moved), "rules": [r.rule_id for r in report.results if not r.passed and r.severity.value == "blocking"]}
        _write_state(ctx.state_path, state)
        logger.error("run %s rejected: %s; the file is in %s", ctx.run_key, ValidationError(report), moved)
        raise ValidationError(report)
    subset = Path(cfg.paths.interim_dir) / "validated_subset.parquet"
    with atomic_path(subset) as temporary:
        frame.to_parquet(temporary, index=False)
    return {
        "subset_path": str(subset), "rows_file": report.rows_file, "rows_subset": report.rows_subset, "wells_subset": report.wells_subset,
        "first_period_key": report.first_period_key, "last_period_key": report.last_period_key, "source_sha256": report.source_sha256,
        "warnings": [r.rule_id for r in report.results if not r.passed and r.severity.value == "warning"],
    }


def load(ctx: RunContext) -> dict:
    """Load the validated subset into SQLite in one transaction and open the run record (RF05, RF06)."""
    cfg = ctx.cfg
    done = _task_result(ctx, "validate")
    download_result = _task_result(ctx, "download")
    remote = _task_result(ctx, "check_publication")["remote"]
    frame = pd.read_parquet(done["subset_path"])
    conn = connect(cfg.paths.warehouse)
    try:
        result = load_validated_subset(conn, frame, ctx.run_key, cfg)
        record_run(conn, {
            "run_key": ctx.run_key, "started_at": ctx.started_at.isoformat(timespec="seconds"), "status": "running",
            "source_url": remote["url"], "source_etag": remote["etag"], "source_last_modified": remote["last_modified"],
            "source_size": download_result["size"], "source_sha256": download_result["sha256"], "last_period_key": result.last_period_key,
            "rows_subset": result.rows, "wells_subset": result.wells, "revised_rows": result.revised_rows,
        })
        record_validation_results(conn, read_report(Path(cfg.paths.reports_dir) / "validation" / "history" / f"{ctx.run_key}.json"))
    finally:
        conn.close()
    return {"rows": result.rows, "wells": result.wells, "last_period_key": result.last_period_key, "revised_rows": result.revised_rows, "controls": len(result.checks)}


def backtest(ctx: RunContext) -> dict:
    """Walk-forward backtest of the six methods, their bands, the summary and the method selection."""
    return run_backtest(ctx)


def forecast(ctx: RunContext) -> dict:
    """The 12-month P10/P50/P90 of every active series at the last published month."""
    return run_production_forecast(ctx)


def export(ctx: RunContext) -> dict:
    """Rebuild the model marts and write the star schema; the files are read back and checked (RF17, AC17)."""
    cfg = ctx.cfg
    sha = _task_result(ctx, "download")["sha256"]
    conn = connect(cfg.paths.warehouse)
    try:
        # The exported run table must show this run as done, and only the HTML and the report are left; if one of
        # them fails the task wrapper marks the run failed in SQLite and the next run exports again.
        record_run(conn, {"run_key": ctx.run_key, "status": "ok", "finished_at": _now_text(), "message": "ok"})
        paths = export_star_schema(conn, cfg.paths.outputs_dir, MODEL, ctx.run_key, sha, ATTRIBUTION)
    finally:
        conn.close()
    problems = verify_star_schema(cfg.paths.outputs_dir, MODEL)
    if problems:
        raise ExportError(f"the exported star schema breaks its contract: {problems[0]} ({len(problems)} problems)")
    big = oversized_files(paths)
    if big:
        logger.warning("exported files over the size limit: %s", ", ".join(p.name for p in big))
    return {"files": [str(p) for p in paths], "oversized": [p.name for p in big], "bytes": sum(p.stat().st_size for p in paths)}


def render_dashboard(ctx: RunContext) -> dict:
    """Generate the HTML design of the report from the semantic model and the exported tables (RF18)."""
    path = render_design(MODEL, ctx.cfg.paths.outputs_dir, ctx.cfg.paths.dashboard_html, ATTRIBUTION)
    return {"html": str(path), "bytes": path.stat().st_size}


def report(ctx: RunContext) -> dict:
    """Write the backtest summary and close the run: the publication is marked loaded only now (RF14, RF19)."""
    cfg = ctx.cfg
    conn = connect(cfg.paths.warehouse)
    try:
        summary = read_summary(conn)
    finally:
        conn.close()
    criteria = evaluate_criteria(summary, cfg.criteria)
    json_path, md_path = write_summary(criteria, summary, cfg.paths.reports_dir)
    mark_manifest(_manifest_path(cfg), ctx.run_key, "loaded")
    return {"summary_json": str(json_path), "summary_md": str(md_path), "passed": criteria["passed"]}


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec("check_publication", check_publication, 3, 10, 5, short_circuit=True),
    TaskSpec("download", download, 3, 15, 30),
    TaskSpec("validate", validate, 0, 0, 15),
    TaskSpec("load", load, 1, 5, 20),
    TaskSpec("backtest", backtest, 1, 10, 120),
    TaskSpec("forecast", forecast, 1, 10, 45),
    TaskSpec("export", export, 1, 5, 10),
    TaskSpec("render_dashboard", render_dashboard, 1, 5, 10),
    TaskSpec("report", report, 1, 5, 5),
)
TASK_IDS = tuple(t.task_id for t in TASKS)


# --- running tasks ----------------------------------------------------------------------------------------------------


def _spec(task_id: str) -> TaskSpec:
    for spec in TASKS:
        if spec.task_id == task_id:
            return spec
    raise ValueError(f"unknown task {task_id!r}; expected one of {', '.join(TASK_IDS)}")


def _run_spec(spec: TaskSpec, ctx: RunContext) -> dict:
    started = time.perf_counter()
    logger.info("task %s start (run %s)", spec.task_id, ctx.run_key)
    try:
        result = spec.func(ctx)
    except ValidationError:
        raise
    except BaseException as error:
        message = f"{spec.task_id}: {type(error).__name__}: {error}"[:500]
        state = _read_state(ctx.state_path)
        state["status"] = "failed"
        state.setdefault("tasks", {})[spec.task_id] = {"status": "failed", "error": message}
        _write_state(ctx.state_path, state)
        if _has_record(ctx):
            _record(ctx, status="failed", finished_at=_now_text(), message=message)
        logger.error("task %s failed after %.1f s: %s", spec.task_id, time.perf_counter() - started, message)
        raise
    # A task that reports its own stage times (the backtest and the forecast) keeps them as ``stage_seconds``;
    # ``seconds`` is always the wall time of the whole task.
    stages = {"stage_seconds": result["seconds"]} if isinstance(result.get("seconds"), dict) else {}
    result = {**result, **stages, "seconds": round(time.perf_counter() - started, 2)}
    _save_task(ctx, spec.task_id, result, status=result.get("status"))
    logger.info("task %s end in %.1f s", spec.task_id, result["seconds"])
    return result


def run_task(task_id: str, run_id: str | None = None, cfg: PipelineConfig | None = None, *, now: datetime | None = None) -> dict:
    """Run one task of the run `run_id` (a new run if none) and return what it produced.

    A run that finishes without a state of its own (the last task) is marked ``ok`` in the state file.
    """
    spec = _spec(task_id)
    ctx = _context(cfg or load_config(), run_id, now)
    result = _run_spec(spec, ctx)
    if task_id == TASK_IDS[-1]:
        state = _read_state(ctx.state_path)
        state["status"] = "ok"
        _write_state(ctx.state_path, state)
    return result


def run_all(
    cfg: PipelineConfig, adopt: Path | None = None, only: list[str] | None = None, start: str | None = None,
    *, run_key: str | None = None, now: datetime | None = None, on_task: Callable[[str, dict], None] | None = None,
) -> list[dict]:
    """Run the tasks in order: all, only the listed ones, or from `start` on; stops after an unchanged publication.

    Returns one ``{"task", "result"}`` per task that ran; `on_task` is called with each one as it ends, so a
    caller can show progress even if a later task fails. ``ValidationError`` is not caught: the run was rejected.
    """
    ids = list(TASK_IDS)
    if start is not None:
        _spec(start)
        ids = ids[ids.index(start):]
    if only:
        for task_id in only:
            _spec(task_id)
        ids = [i for i in ids if i in only]
    ctx = _context(cfg, run_key, now, adopt)
    outcome = []
    for task_id in ids:
        spec = _spec(task_id)
        result = _run_spec(spec, ctx)
        outcome.append({"task": task_id, "result": result})
        if on_task is not None:
            on_task(task_id, result)
        if spec.short_circuit and not result.get("changed", True):
            logger.info("run %s ends after %s: the publication did not change", ctx.run_key, task_id)
            break
    else:
        if ids and ids[-1] == TASK_IDS[-1]:
            state = _read_state(ctx.state_path)
            state["status"] = "ok"
            _write_state(ctx.state_path, state)
    return outcome
