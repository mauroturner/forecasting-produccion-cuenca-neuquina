"""The SQLite warehouse: connection, SQL runner, load of the validated subset, controls (RF05, RF06).

Rules of the runner (docs/plan.md section 5, D04):

- autocommit connection (``isolation_level=None``), transactions are explicit ``BEGIN IMMEDIATE``;
- ``journal_mode=DELETE`` (WAL does not behave on Docker Desktop mounts), ``synchronous=FULL``;
- never ``executescript()``: it commits the open transaction first. SQL files are split into
  statements and executed one by one, so a failure can roll the whole load back;
- the marts are rebuilt with ``DROP TABLE IF EXISTS`` + ``CREATE TABLE AS``, which SQLite also rolls back.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from oilgas.config import PipelineConfig, load_config
from oilgas.validate import SEVERITY_ES, PreviousLoad, ValidationReport

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
CHECK_GROUPS = ("production", "model")
SAMPLE_LIMIT = 5
# Built in this order after raw_monthly_production is replaced.
PRODUCTION_BUILD = (
    "staging/stg_monthly_production.sql",
    "marts/production/dim_calendar.sql",
    "marts/production/dim_company.sql",
    "marts/production/dim_well.sql",
    "marts/production/fact_production_monthly.sql",
    "staging/period_totals.sql",
)
RUN_COLUMNS = (
    "started_at", "finished_at", "status", "source_url", "source_etag", "source_last_modified",
    "source_size", "source_sha256", "last_period_key", "rows_subset", "wells_subset", "revised_rows",
    "message",
)


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    violations: int
    sample: list[tuple]


@dataclass(frozen=True)
class LoadResult:
    rows: int
    wells: int
    last_period_key: int
    revised_rows: int
    checks: list[CheckResult]


class EmptySubsetError(RuntimeError):
    """The validated subset has no rows: the load was rolled back and the warehouse kept what it had."""

    def __init__(self, run_key: str) -> None:
        super().__init__(f"The load of {run_key} was rolled back: the validated subset has no rows")


class CheckFailedError(RuntimeError):
    """A control returned rows: the load was rolled back."""

    def __init__(self, checks: list[CheckResult]) -> None:
        self.checks = checks
        failing = [c for c in checks if c.violations]
        detail = "; ".join(f"{c.check_id}: {c.violations} rows, e.g. {c.sample[:2]}" for c in failing)
        super().__init__(f"The load was rolled back; controls with violations: {detail}")


# --- connection and SQL files -----------------------------------------------------------------------


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating the folder and the file) the warehouse in autocommit mode with the project's pragmas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _has_sql(text: str) -> bool:
    """True if `text` has anything besides whitespace, semicolons and comments."""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif ch.isspace() or ch == ";":
            i += 1
        else:
            return True
    return False


def split_statements(sql_text: str) -> list[str]:
    """Split a SQL file into statements, keeping semicolons inside strings, comments and triggers."""
    statements: list[str] = []
    buffer = ""
    for line in sql_text.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if _has_sql(buffer):
                statements.append(buffer.strip())
            buffer = ""
    if _has_sql(buffer):  # a last statement without its semicolon
        statements.append(buffer.strip())
    return statements


def run_sql_file(conn: sqlite3.Connection, path: Path, params: Mapping[str, object] | None = None) -> None:
    """Execute the statements of a SQL file one by one, binding the named parameters it uses."""
    text = Path(path).read_text(encoding="utf-8")
    for statement in split_statements(text):
        conn.execute(statement, dict(params or {}))


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the tables of ``sql/schema`` that do not exist yet (idempotent; keeps the data)."""
    for path in sorted((SQL_DIR / "schema").glob("*.sql")):
        run_sql_file(conn, path)


# --- controls ---------------------------------------------------------------------------------------


def run_checks(conn: sqlite3.Connection, group: Literal["production", "model"]) -> list[CheckResult]:
    """Run the controls of a group; each file selects the rows that break its rule (none = passes)."""
    if group not in CHECK_GROUPS:
        raise ValueError(f"unknown check group {group!r}; expected one of {', '.join(CHECK_GROUPS)}")
    results = []
    for path in sorted((SQL_DIR / "checks" / group).glob("chk_*.sql")):
        statements = split_statements(path.read_text(encoding="utf-8"))
        if len(statements) != 1:
            raise ValueError(f"{path.name} must hold exactly one SELECT, found {len(statements)} statements")
        select = statements[0].rstrip().rstrip(";")
        violations = conn.execute(f"SELECT COUNT(*) FROM ({select})").fetchone()[0]
        sample = conn.execute(f"SELECT * FROM ({select}) LIMIT {SAMPLE_LIMIT}").fetchall() if violations else []
        results.append(CheckResult(path.stem, int(violations), sample))
    return results


# --- load -------------------------------------------------------------------------------------------


def _sql_values(frame: pd.DataFrame) -> list[tuple]:
    """The frame as Python tuples SQLite can store: missing values as None, dates as ISO text."""
    columns = []
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_datetime64_any_dtype(series):
            fmt = "%Y-%m-%d" if name == "period_end" else "%Y-%m-%d %H:%M:%S.%f"
            series = series.dt.strftime(fmt)
        columns.append(series.astype(object).where(series.notna(), None).tolist())
    return list(zip(*columns, strict=True))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _sql_params(cfg: PipelineConfig, run_key: str, previous_last: int | None) -> dict[str, object]:
    v = cfg.validation
    return {
        "run_key": run_key,
        "previous_last_period_key": previous_last,
        "oil_ceiling_m3": v.oil_ceiling_m3,
        "gas_ceiling_thousand_m3": v.gas_ceiling_thousand_m3,
        "lon_min": v.basin_lon[0], "lon_max": v.basin_lon[1],
        "lat_min": v.basin_lat[0], "lat_max": v.basin_lat[1],
        "depth_min_m": v.depth_valid_m[0], "depth_max_m": v.depth_valid_m[1],
    }


def load_validated_subset(
    conn: sqlite3.Connection, frame: pd.DataFrame, run_key: str, cfg: PipelineConfig | None = None
) -> LoadResult:
    """Replace the warehouse content with the validated subset, in one transaction.

    Counts the revisions against the content being replaced, replaces ``raw_monthly_production``,
    rebuilds staging and the production marts and runs the controls. If anything fails, including a
    control, the transaction is rolled back and the warehouse keeps exactly what it had.
    """
    cfg = cfg or load_config()
    columns = ", ".join(frame.columns)
    marks = ", ".join("?" for _ in frame.columns)
    values = _sql_values(frame)
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        previous_last = conn.execute("SELECT MAX(period_key) FROM raw_monthly_production").fetchone()[0]
        params = _sql_params(cfg, run_key, previous_last)

        conn.execute("DROP TABLE IF EXISTS temp.tmp_raw_new")
        conn.execute("CREATE TEMP TABLE tmp_raw_new AS SELECT * FROM raw_monthly_production WHERE 0")
        conn.executemany(f"INSERT INTO tmp_raw_new ({columns}) VALUES ({marks})", values)
        run_sql_file(conn, SQL_DIR / "staging" / "load_revisions.sql", params)
        revised = conn.execute("SELECT COALESCE(SUM(rows_changed), 0) FROM load_revisions WHERE run_key = ?", (run_key,)).fetchone()[0]

        conn.execute("DELETE FROM raw_monthly_production")
        conn.execute(f"INSERT INTO raw_monthly_production ({columns}) SELECT {columns} FROM tmp_raw_new")
        conn.execute("DROP TABLE temp.tmp_raw_new")
        for name in PRODUCTION_BUILD:
            run_sql_file(conn, SQL_DIR / name, params)

        checks = run_checks(conn, "production")
        if any(c.violations for c in checks):
            raise CheckFailedError(checks)
        rows, wells, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT well_id), MAX(period_key) FROM raw_monthly_production"
        ).fetchone()
        # An empty subset would wipe the warehouse; refuse it before the commit, not after.
        if not rows:
            raise EmptySubsetError(run_key)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return LoadResult(int(rows), int(wells), int(last), int(revised), checks)


def previous_load(conn: sqlite3.Connection) -> PreviousLoad | None:
    """What the warehouse holds now, for the next validation (V09, V10, V20); None if it is empty."""
    if not _table_exists(conn, "raw_monthly_production"):
        return None
    rows, wells, last = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT well_id), MAX(period_key) FROM raw_monthly_production"
    ).fetchone()
    if not rows:
        return None
    totals = pd.read_sql_query(
        "SELECT period_key, COALESCE(SUM(oil_m3), 0) AS oil_m3, COALESCE(SUM(gas_thousand_m3), 0) AS gas_thousand_m3 "
        "FROM raw_monthly_production GROUP BY period_key ORDER BY period_key",
        conn,
    )
    return PreviousLoad(int(rows), int(wells), int(last), totals)


# --- run records ------------------------------------------------------------------------------------


def record_run(conn: sqlite3.Connection, run: dict) -> None:
    """Insert the run in ``pipeline_runs`` or update only the columns given for its ``run_key``."""
    if "run_key" not in run:
        raise ValueError("a run record needs a run_key")
    unknown = sorted(set(run) - {"run_key", *RUN_COLUMNS})
    if unknown:
        raise ValueError(f"unknown pipeline_runs column {unknown[0]!r}")
    given = [c for c in RUN_COLUMNS if c in run]
    names = ", ".join(["run_key", *given])
    marks = ", ".join("?" for _ in range(len(given) + 1))
    update = ", ".join(f"{c} = excluded.{c}" for c in given) or "run_key = run_key"
    conn.execute(
        f"INSERT INTO pipeline_runs ({names}) VALUES ({marks}) ON CONFLICT(run_key) DO UPDATE SET {update}",
        [run["run_key"], *(run[c] for c in given)],
    )


def record_validation_results(conn: sqlite3.Connection, report: ValidationReport) -> None:
    """Store the rule results of a run, replacing the ones of the same ``run_key``."""
    rows = [
        (report.run_key, r.rule_id, r.name_es, SEVERITY_ES[r.severity], int(r.passed), r.rows_affected,
         r.wells_affected, json.dumps(r.examples, ensure_ascii=False))
        for r in report.results
    ]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM validation_results WHERE run_key = ?", (report.run_key,))
        conn.executemany("INSERT INTO validation_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
