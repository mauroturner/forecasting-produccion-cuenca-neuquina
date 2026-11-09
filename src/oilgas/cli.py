"""Command line of the pipeline: ``python -m oilgas <command>`` (plan section 15).

``run`` walks the same ``pipeline.TASKS`` as the Airflow DAG, in the same order and with the same
functions, so Windows can run the whole flow without Airflow. Exit codes: 0 ok (also an unchanged
publication), 1 a task failed, 2 wrong usage or configuration, 3 the publication was rejected by the
validation (the warehouse and the exported files are as they were).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

import pandas as pd

from oilgas.config import PROJECT_ROOT, PipelineConfig, load_config
from oilgas.ablation import run_ablation
from oilgas.dashboard.semantic_model import MODEL
from oilgas.docs import COLUMNS_END, COLUMNS_START, METHODS_END, METHODS_START, render_dictionary_tables, render_method_tables
from oilgas.figures import make_figures
from oilgas.pipeline import TASK_IDS, TASKS, UsageError, make_run_key, run_all, run_task
from oilgas.reporting import sync_block
from oilgas.validate import ValidationError
from oilgas.warehouse import connect

RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REJECTED = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m oilgas", description="Oil and gas production per well: Arps curves versus machine learning.")
    parser.add_argument("-v", "--verbose", action="store_true", help="also log the details of every step")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the tasks in order: " + ", ".join(TASK_IDS))
    run.add_argument("--config", type=Path, help="configuration file (default: $OILGAS_CONFIG or config/pipeline.toml)")
    run.add_argument("--adopt", type=Path, metavar="CSV", help="use this already downloaded file instead of downloading it (not with source.mode = local, which names its own file)")
    run.add_argument("--only", nargs="+", choices=TASK_IDS, metavar="TASK", help="run only these tasks")
    run.add_argument("--from", dest="start", choices=TASK_IDS, metavar="TASK", help="start at this task")
    run.add_argument("--run-key", help="continue the run with this key (needed with --from or --only after the first task)")

    task = commands.add_parser("task", help="run one task of a run")
    task.add_argument("task", choices=TASK_IDS, metavar="TASK")
    task.add_argument("--config", type=Path)
    task.add_argument("--run-key", help="the run it belongs to (a new run if omitted)")

    sync = commands.add_parser("docs-sync", help="copy the backtest results block into the README and fill the generated tables of docs/")
    sync.add_argument("--config", type=Path)

    figures = commands.add_parser("figures", help="draw the figures of the documentation (docs/figures/*.png) from the last run")
    figures.add_argument("--config", type=Path)

    ablation = commands.add_parser("ablation-fracture", help="compare the machine learning with and without fracture features (RF21, D15)")
    ablation.add_argument("--config", type=Path)
    ablation.add_argument("--wells", type=int, metavar="N", help="a fixed sample of N wells instead of the configured ones (0 = all)")

    fixture = commands.add_parser("make-fixture", help="write a synthetic publication for tests and quick runs")
    fixture.add_argument("output", type=Path, metavar="OUTPUT.csv")
    fixture.add_argument("--wells", type=int, default=60)
    fixture.add_argument("--seed", type=int, default=0)
    return parser


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _fail(text: str) -> None:
    sys.stderr.write(text + "\n")


def _brief(result: dict) -> str:
    """The few figures of a task result worth a line."""
    keys = ("changed", "status", "rows", "wells", "last_period_key", "forecast_rows", "pairs_evaluated", "bytes", "how")
    return ", ".join(f"{k}={result[k]}" for k in keys if k in result)


def docs_sync(cfg: PipelineConfig) -> bool:
    """Copy ``reports/backtest_summary.md`` between the result markers of the README; True if the README changed."""
    summary = Path(cfg.paths.reports_dir) / "backtest_summary.md"
    if not summary.exists():
        raise FileNotFoundError(f"{summary} does not exist: run the pipeline first")
    return sync_block(cfg.paths.readme, RESULTS_START, RESULTS_END, summary.read_text(encoding="utf-8"))


def sync_generated_docs(cfg: PipelineConfig) -> list[tuple[str, bool]]:
    """Fill the generated tables of ``docs/``: the dictionary's columns and the model card's results; a missing document is skipped.

    Returns ``(file name, changed)`` for each document that exists.
    """
    docs_dir = Path(cfg.paths.readme).parent / "docs"
    done: list[tuple[str, bool]] = []
    dictionary = docs_dir / "data-dictionary.md"
    if dictionary.exists():
        done.append((dictionary.name, sync_block(dictionary, COLUMNS_START, COLUMNS_END, render_dictionary_tables(MODEL))))
    card = docs_dir / "model-card.md"
    if card.exists():
        summary_json = Path(cfg.paths.reports_dir) / "backtest_summary.json"
        if not summary_json.exists():
            raise FileNotFoundError(f"{summary_json} does not exist: run the pipeline first")
        summary = pd.DataFrame(json.loads(summary_json.read_text(encoding="utf-8"))["summary"])
        done.append((card.name, sync_block(card, METHODS_START, METHODS_END, render_method_tables(summary))))
    return done


def draw_figures(cfg: PipelineConfig) -> list[Path]:
    """Draw the documentation figures from the warehouse of the last run into ``docs/figures`` next to the README."""
    warehouse = Path(cfg.paths.warehouse)
    if not warehouse.exists():
        raise FileNotFoundError(f"{warehouse} does not exist: run the pipeline first (python -m oilgas run)")
    conn = connect(warehouse)
    try:
        return make_figures(conn, Path(cfg.paths.reports_dir), Path(cfg.paths.readme).parent / "docs" / "figures")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "make-fixture":
        sys.path.insert(0, str(PROJECT_ROOT))  # the generator lives with the tests, next to src/
        from tests.fixtures.make_fixture import make_fixture

        truth = make_fixture(args.output, n_wells=args.wells, seed=args.seed)
        _say(f"wrote {truth.path}: {truth.n_rows} rows, {truth.n_wells} wells in scope")
        return EXIT_OK
    try:
        cfg = load_config(args.config)
    except (ValueError, FileNotFoundError) as error:
        _fail(f"configuration error: {error}")
        return EXIT_USAGE
    try:
        if args.command == "docs-sync":
            _say("README updated" if docs_sync(cfg) else "README already up to date")
            for name, changed in sync_generated_docs(cfg):
                _say(f"{name} updated" if changed else f"{name} already up to date")
            return EXIT_OK
        if args.command == "figures":
            try:
                paths = draw_figures(cfg)
            except ValueError as error:  # the warehouse holds no backtest yet
                _fail(f"error: {error}")
                return EXIT_USAGE
            for path in paths:
                _say(f"wrote {path}")
            return EXIT_OK
        if args.command == "ablation-fracture":
            result = run_ablation(cfg, args.wells)
            _say(f"{result['wells']} wells, {result['pairs']} pairs per model, {result['seconds']} s: "
                 f"{result['cells_improved']} of {result['cells']} cells improve; the fracture data "
                 f"{'enter' if result['add_to_base'] else 'do not enter'} the base model")
            _say(f"wrote {result['json']}")
            _say(f"wrote {result['markdown']}")
            return EXIT_OK
        if args.command == "task":
            result = run_task(args.task, args.run_key, cfg)
            _say(f"{args.task}: {_brief(result)}")
            return EXIT_OK
        def show(task_id: str, result: dict) -> None:
            _say(f"{task_id:<18} {result.get('seconds', 0):>8.1f} s  {_brief(result)}")

        outcome = run_all(cfg, adopt=args.adopt, only=args.only, start=args.start, run_key=args.run_key, on_task=show)
        if outcome and outcome[-1]["task"] == TASKS[0].task_id and not outcome[-1]["result"].get("changed", True):
            _say(f"unchanged: the publication is the one already loaded ({outcome[-1]['result'].get('status')})")
        return EXIT_OK
    except ValidationError as error:
        _fail(f"rejected: {error}")
        return EXIT_REJECTED
    except (FileNotFoundError, UsageError) as error:
        _fail(f"error: {error}")
        return EXIT_USAGE
    except Exception as error:  # a task failed: its record is in the run state
        _fail(f"failed: {type(error).__name__}: {error}")
        if args.verbose:
            _fail("".join(traceback.format_exception(error)).rstrip())
        return EXIT_FAILED


__all__ = ["build_parser", "docs_sync", "draw_figures", "sync_generated_docs", "main", "make_run_key"]
