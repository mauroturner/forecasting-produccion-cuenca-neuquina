"""The star schema for Power BI: model marts in SQLite and one Parquet file per table (RF17, plan section 13).

``build_model_marts`` rebuilds the model dimensions and facts from the ``model_*`` tables with the SQL
files of ``sql/marts/model`` and runs the model controls in the same transaction: if one returns rows,
the marts keep what they had. ``export_star_schema`` writes each table of the semantic model with the
Arrow schema the model declares and the run, source and attribution as file metadata.
``verify_star_schema`` reads the files back and checks the contract the report relies on (AC17).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from oilgas.dashboard.semantic_model import ARROW_TYPES, SemanticModel, Table, arrow_schema, validate_model
from oilgas.files import write_atomic
from oilgas.warehouse import SQL_DIR, CheckFailedError, apply_schema, run_checks, run_sql_file

logger = logging.getLogger(__name__)

MAX_PARQUET_BYTES = 25 * 1024 * 1024  # a versioned file must stay under GitHub's limits (RNF09)
MAX_ORIGINS = 12  # origins kept in the facts; fewer when the files that grow with them would pass the limit
ORIGIN_SCOPED = ("fact_forecast", "fact_well_fit")  # the tables that grow with each origin
MODEL_BUILD = tuple(
    f"marts/model/{name}.sql"
    for name in (
        "dim_fluid", "dim_method", "dim_horizon", "dim_origin", "dim_pipeline_run",
        "fact_forecast", "fact_well_fit", "fact_fitted_curve", "fact_backtest_metrics", "fact_model_summary", "fact_validation",
    )
)
PRODUCTION_TABLES = ("dim_calendar", "dim_well", "dim_company", "fact_production_monthly")
METADATA_KEYS = ("oilgas.run_key", "oilgas.source_sha256", "oilgas.attribution")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def build_model_marts(conn: sqlite3.Connection, max_origins: int = MAX_ORIGINS) -> None:
    """Rebuild the model dimensions and facts and run the model controls, all in one transaction.

    Keeps the latest `max_origins` origins of the forecast. Needs the production marts (a loaded
    publication). If a control returns rows, ``CheckFailedError`` is raised and the marts keep what they had.
    """
    missing = [t for t in PRODUCTION_TABLES if not _table_exists(conn, t)]
    if missing:
        raise RuntimeError(f"the production marts {', '.join(missing)} do not exist: load a validated publication before exporting")
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        for name in MODEL_BUILD:
            run_sql_file(conn, SQL_DIR / name, {"max_origins": max_origins})
        checks = run_checks(conn, "model")
        failing = [c for c in checks if c.violations]
        for c in failing:
            logger.error("model control %s: violations=%d sample=%s", c.check_id, c.violations, c.sample)
        if failing:
            raise CheckFailedError(checks)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    logger.info("model marts rebuilt: %d controls passed", len(checks))


def _read_table(conn: sqlite3.Connection, table: Table) -> pd.DataFrame:
    columns = ", ".join(table.column_names)
    order = ", ".join(table.key)
    return pd.read_sql_query(f"SELECT {columns} FROM {table.name} ORDER BY {order}", conn)


def _arrow_table(frame: pd.DataFrame, table: Table) -> pa.Table:
    """The frame as an Arrow table with the model's schema; a key with a missing value is an error."""
    for key in table.key:
        if frame[key].isna().any():
            raise ValueError(f"{table.name}[{key}] has missing values: a key cannot")
    arrays = []
    for column in table.columns:
        series, kind = frame[column.name], ARROW_TYPES[column.dtype]
        if column.dtype == "date":
            values = pd.to_datetime(series, errors="raise").dt.date.astype(object).where(series.notna(), None)
            arrays.append(pa.array(values, type=kind))
        elif column.dtype == "bool":
            arrays.append(pa.Array.from_pandas(series.astype("Int64").astype("boolean"), type=kind))
        elif column.dtype in ("int32", "int64"):
            arrays.append(pa.Array.from_pandas(pd.array(series, dtype="Int64"), type=kind))
        elif column.dtype == "float64":
            arrays.append(pa.Array.from_pandas(pd.to_numeric(series).astype("float64"), type=kind))
        else:
            arrays.append(pa.array(series.astype(object).where(series.notna(), None), type=kind))
    return pa.Table.from_arrays(arrays, schema=arrow_schema(table))


def _close_run(frame: pd.DataFrame, closing_run: dict) -> pd.DataFrame:
    """The run table with the run being exported shown as finished, as SQLite will say once the files are checked."""
    frame = frame.copy()
    mine = frame["run_key"] == closing_run["run_key"]
    for column, value in closing_run.items():
        if column != "run_key":
            frame.loc[mine, column] = value
    return frame


def _serialize(conn: sqlite3.Connection, table: Table, metadata: dict[str, str], closing_run: dict | None = None) -> bytes:
    """The Parquet file of a table as bytes (so its size is known before anything is written)."""
    frame = _read_table(conn, table)
    if closing_run is not None and table.name == "dim_pipeline_run":
        frame = _close_run(frame, closing_run)
    arrow = _arrow_table(frame, table).replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    pq.write_table(arrow, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def export_star_schema(
    conn: sqlite3.Connection, out_dir: Path, model: SemanticModel, run_key: str, source_sha256: str, attribution: str,
    closing_run: dict | None = None,
) -> list[Path]:
    """Rebuild the marts and write one Parquet file per table of `model`; returns the paths in the model's order.

    ``closing_run`` (its ``run_key`` and the columns to set) is applied to the exported run table only, so the
    files show the run as finished while SQLite keeps it "running" until the caller has checked them.

    The controls run before any file is written, and so does the size check: if a table that grows with
    each origin would pass ``MAX_PARQUET_BYTES``, fewer origins are kept (down to the latest one) and the
    older ones stay in SQLite. Each file is replaced atomically.
    """
    problems = validate_model(model)
    if problems:
        raise ValueError(f"the semantic model is inconsistent: {problems[0]}")
    metadata = {"oilgas.run_key": run_key, "oilgas.source_sha256": source_sha256, "oilgas.attribution": attribution}
    max_origins = MAX_ORIGINS
    while True:
        build_model_marts(conn, max_origins)
        blobs = {table.name: _serialize(conn, table, metadata, closing_run) for table in model.tables}
        heavy = [name for name in ORIGIN_SCOPED if name in blobs and len(blobs[name]) > MAX_PARQUET_BYTES]
        if not heavy or max_origins == 1:
            break
        fit = min(MAX_PARQUET_BYTES / len(blobs[name]) for name in heavy)
        smaller = max(1, min(max_origins - 1, int(max_origins * fit * 0.9)))
        logger.warning(
            "%s would weigh %d bytes (limit %d): keeping the latest %d origins instead of %d",
            ", ".join(heavy), max(len(blobs[name]) for name in heavy), MAX_PARQUET_BYTES, smaller, max_origins,
        )
        max_origins = smaller
    out_dir = Path(out_dir)
    paths = []
    for table in model.tables:
        path = write_atomic(out_dir / f"{table.name}.parquet", blobs[table.name])
        logger.info("exported %s: %d rows, %d bytes", path.name, pq.ParquetFile(path).metadata.num_rows, path.stat().st_size)
        paths.append(path)
    return paths


def oversized_files(paths: list[Path], limit: int | None = None) -> list[Path]:
    """The files larger than `limit` bytes (default ``MAX_PARQUET_BYTES``; RNF09: a versioned Parquet weighs at most 25 MB)."""
    limit = MAX_PARQUET_BYTES if limit is None else limit
    return [p for p in paths if Path(p).stat().st_size > limit]


def verify_star_schema(out_dir: Path, model: SemanticModel) -> list[str]:
    """Read the Parquet files back and list every way they break the contract (empty when they keep it, AC17).

    Checks: the model itself (keys, relationships, DAX references, pages), the schema and metadata of every
    file, non-null keys, unique grains and referential integrity of every relationship (all foreign keys
    exist, none is empty).
    """
    problems = [f"model: {p}" for p in validate_model(model)]
    out_dir = Path(out_dir)
    frames: dict[str, pd.DataFrame] = {}
    for table in model.tables:
        path = out_dir / f"{table.name}.parquet"
        if not path.exists():
            problems.append(f"{table.name}: {path.name} does not exist")
            continue
        file = pq.ParquetFile(path)
        if not file.schema_arrow.equals(arrow_schema(table), check_metadata=False):
            problems.append(f"{table.name}: the schema of {path.name} differs from the model's")
            continue
        metadata = {k.decode(): v.decode() for k, v in (file.schema_arrow.metadata or {}).items()}
        missing = [k for k in METADATA_KEYS if not metadata.get(k)]
        if missing:
            problems.append(f"{table.name}: metadata {', '.join(missing)} missing")
        frame = file.read().to_pandas()
        frames[table.name] = frame
        for key in table.key:
            if frame[key].isna().any():
                problems.append(f"{table.name}[{key}]: has empty values")
        if frame.duplicated(list(table.key)).any():
            problems.append(f"{table.name}: the key {list(table.key)} is not unique")
    for r in model.relationships:
        if r.dim_table not in frames or r.fact_table not in frames:
            continue
        fact_values = frames[r.fact_table][r.fact_column]
        known = set(frames[r.dim_table][r.dim_column].dropna())
        empty = int(fact_values.isna().sum())
        orphans = int((~fact_values.dropna().isin(known)).sum())
        if empty or orphans:
            problems.append(f"{r.rel_id} {r.fact_table}[{r.fact_column}]: {orphans} values not in {r.dim_table}, {empty} empty")
    return problems
