"""Command line of the pipeline: ``python -m oilgas <command>`` (plan section 15).

``run`` walks the same ``pipeline.TASKS`` as the Airflow DAG, in the same order and with the same
functions, so Windows can run the whole flow without Airflow. Exit codes: 0 ok (also an unchanged
publication), 1 a task failed, 2 wrong usage or configuration, 3 the publication was rejected by the
validation (the warehouse and the exported files are as they were).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from oilgas.config import PROJECT_ROOT, PipelineConfig, load_config
from oilgas.pipeline import TASK_IDS, TASKS, make_run_key, run_all, run_task
from oilgas.reporting import sync_block
from oilgas.validate import ValidationError

RESULTS_START = "<!-- results:start -->"
RESULTS_END = "<!-- results:end -->"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REJECTED = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m oilgas", description="Oil and gas production per well: Arps curves versus machine learning.")
    parser.add_argument("-v", "--verbose", action="store_true", help="also log the details of every step")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run the tasks in order: " + ", ".join(TASK_IDS))
    run.add_argument("--config", type=Path, help="configuration file (default: $OILGAS_CONFIG or config/pipeline.toml)")
    run.add_argument("--adopt", type=Path, metavar="CSV", help="use this already downloaded file instead of downloading it")
    run.add_argument("--only", nargs="+", choices=TASK_IDS, metavar="TASK", help="run only these tasks")
    run.add_argument("--from", dest="start", choices=TASK_IDS, metavar="TASK", help="start at this task")
    run.add_argument("--run-key", help="continue the run with this key (needed with --from or --only after the first task)")

    task = commands.add_parser("task", help="run one task of a run")
    task.add_argument("task", choices=TASK_IDS, metavar="TASK")
    task.add_argument("--config", type=Path)
    task.add_argument("--run-key", help="the run it belongs to (a new run if omitted)")

    sync = commands.add_parser("docs-sync", help="copy the backtest results block into the README")
    sync.add_argument("--config", type=Path)

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
    except FileNotFoundError as error:
        _fail(f"error: {error}")
        return EXIT_USAGE
    except Exception as error:  # a task failed: its record is in the run state
        _fail(f"failed: {type(error).__name__}: {error}")
        return EXIT_FAILED


__all__ = ["build_parser", "docs_sync", "main", "make_run_key"]
