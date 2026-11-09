"""Hydraulic fracture features for the ablation (RF21, decision D15).

The fracture file is preliminary ("datos preliminares sujetos a revision") and is not part of the base
model. This module reads it and attaches, to a series panel, dense arrays with what is known about each
well at each month: only fractures whose end date is **at or before** that month count, so a feature at
an origin never uses a fracture finished later (no leakage, as in AC11). A well with no fracture finished
by then has missing values, which the gradient boosting handles natively.

Per well and month: ``frac_stages`` (stages pumped, summed), ``frac_lateral_m`` (the longest lateral
length reported; 0 means "not reported" and is missing), ``frac_sand_t`` (national plus imported sand,
summed), ``frac_water_m3`` (water injected, summed) and ``frac_months_since`` (months since the latest
fracture ended).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from oilgas.schema import period_index_of
from oilgas.series import SeriesPanel, build_panel

FRACTURE_FEATURES = ("frac_stages", "frac_lateral_m", "frac_sand_t", "frac_water_m3", "frac_months_since")
REQUIRED_COLUMNS = (
    "idpozo", "fecha_fin_fractura", "cantidad_fracturas", "longitud_rama_horizontal_m",
    "arena_bombeada_nacional_tn", "arena_bombeada_importada_tn", "agua_inyectada_m3",
)


@dataclass(frozen=True)
class FractureTable:
    """One entry per fracture job with a readable end date; all arrays have the same length."""

    well_id: np.ndarray  # int64
    end_index: np.ndarray  # int64, month index of the end date (year * 12 + month - 1)
    stages: np.ndarray  # float64
    lateral_m: np.ndarray  # float64, NaN where the file says 0 (not reported)
    sand_t: np.ndarray  # float64, national + imported
    water_m3: np.ndarray  # float64
    rows_dropped: int  # rows without a readable end date (nobody can prove they are not in the future)


def _numbers(frame: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)


def read_fracture_csv(path: Path) -> FractureTable:
    """Read the fracture file; raises ``ValueError`` naming the first required column that is missing."""
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False, na_values=[""])
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{path}: the fracture file lacks the column {missing[0]!r}")
    end = pd.to_datetime(frame["fecha_fin_fractura"], errors="coerce")
    well = pd.to_numeric(frame["idpozo"], errors="coerce")
    keep = (end.notna() & well.notna()).to_numpy()
    frame, end = frame[keep].reset_index(drop=True), end[keep].reset_index(drop=True)
    lateral = _numbers(frame, "longitud_rama_horizontal_m")
    sand = np.nan_to_num(_numbers(frame, "arena_bombeada_nacional_tn")) + np.nan_to_num(_numbers(frame, "arena_bombeada_importada_tn"))
    return FractureTable(
        well_id=pd.to_numeric(frame["idpozo"]).to_numpy(dtype=np.int64),
        end_index=period_index_of(end.dt.year.to_numpy(dtype=np.int64), end.dt.month.to_numpy(dtype=np.int64)),
        stages=_numbers(frame, "cantidad_fracturas"),
        lateral_m=np.where(lateral > 0, lateral, np.nan),
        sand_t=sand,
        water_m3=_numbers(frame, "agua_inyectada_m3"),
        rows_dropped=int((~keep).sum()),
    )


def attach_fracture(panel: SeriesPanel, table: FractureTable) -> SeriesPanel:
    """A copy of the panel with ``fracture``: for each feature a ``(wells, months)`` array of what is known at each month.

    A fracture finished before the first month of the panel counts from the first month; one finished after
    the last month never appears. Wells of the file that are not in the panel are ignored.
    """
    n_wells, n_months = len(panel.well_ids), len(panel.period_index)
    first = int(panel.period_index[0])
    row_of = {int(w): i for i, w in enumerate(panel.well_ids)}
    rows = np.array([row_of.get(int(w), -1) for w in table.well_id], dtype=np.int64)
    cols = np.maximum(table.end_index - first, 0)
    use = (rows >= 0) & (cols < n_months)
    rows, cols = rows[use], cols[use]

    def added(values: np.ndarray) -> np.ndarray:
        grid = np.zeros((n_wells, n_months))
        np.add.at(grid, (rows, cols), np.nan_to_num(values[use]))
        return np.cumsum(grid, axis=1)

    count = np.zeros((n_wells, n_months))
    np.add.at(count, (rows, cols), 1.0)
    seen = np.cumsum(count, axis=1) > 0
    longest = np.full((n_wells, n_months), -np.inf)
    np.maximum.at(longest, (rows, cols), np.where(np.isnan(table.lateral_m[use]), -np.inf, table.lateral_m[use]))
    longest = np.maximum.accumulate(longest, axis=1)
    latest_end = np.full((n_wells, n_months), -np.inf)
    np.maximum.at(latest_end, (rows, cols), (table.end_index[use]).astype(np.float64))
    latest_end = np.maximum.accumulate(latest_end, axis=1)

    months = panel.period_index[None, :].astype(np.float64)
    arrays = {
        "frac_stages": np.where(seen, added(table.stages), np.nan),
        "frac_lateral_m": np.where(np.isfinite(longest), longest, np.nan),
        "frac_sand_t": np.where(seen, added(table.sand_t), np.nan),
        "frac_water_m3": np.where(seen, added(table.water_m3), np.nan),
        "frac_months_since": np.where(seen, months - latest_end, np.nan),
    }
    return dataclasses.replace(panel, fracture=arrays)


def fracture_at(panel: SeriesPanel, col: int, rows: np.ndarray) -> dict[str, np.ndarray]:
    """What is known at column `col` about the wells `rows`: one array per feature."""
    return {name: panel.fracture[name][rows, col] for name in FRACTURE_FEATURES}


def model_panel(conn, cfg) -> SeriesPanel:
    """The panel the model tasks use: the base one, plus the fracture arrays when ``cfg.ml.fracture_features`` is on."""
    panel = build_panel(conn, cfg.backtest.well_sample, cfg.backtest.seed)
    if not cfg.ml.fracture_features:
        return panel
    path = Path(cfg.paths.fracture_csv)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: ml.fracture_features needs the fracture file")
    return attach_fracture(panel, read_fracture_csv(path))
