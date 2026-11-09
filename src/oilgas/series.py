"""Dense panels of monthly series (well x month) and the per-series rules (RF07, plan section 8).

The panel has one row per well and one column per calendar month, from the first to the last month
the warehouse holds, for each fluid. A cell is NaN when the well has no row in that month (or its
volume was corrected to null), 0 when the well reported zero. Every computation at a forecast origin
``o`` takes ``row[: col + 1]``, so leaking later months is a matter of never slicing past the origin.

Volumes are m3 (oil, water) or thousand m3 (gas); rates are volume per calendar day (D03).
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

FLUIDS = ("oil", "gas")
VOLUME_COLUMN = {"oil": "oil_m3", "gas": "gas_thousand_m3"}
# Attributes that change month by month: panel name -> column of stg_monthly_production.
CATEGORY_COLUMNS = {"operator": "company_code", "well_type": "well_type", "extraction_method": "extraction_method"}
ACTIVITY_MONTHS = 3  # a series is active when it produced in the origin month or the two before
YOUNG_BELOW = 6
AGE_BUCKETS = ("young", "06-11", "12-23", "24-59", "60+")
ATTRIBUTE_COLUMNS = ("well_code", "province", "formation_name", "sub_resource_type", "lon", "lat", "depth_m")

Segment = Literal["eligible", "young", "inactive"]


@dataclass(frozen=True)
class SeriesPanel:
    well_ids: np.ndarray  # (W,) int64, ascending
    period_index: np.ndarray  # (T,) int64, contiguous months (year * 12 + month - 1)
    days_in_month: np.ndarray  # (T,) int64
    volume: dict[str, np.ndarray]  # fluid -> (W, T) float64
    rate: dict[str, np.ndarray]  # fluid -> (W, T) float64, volume / days_in_month
    water_rate: np.ndarray  # (W, T) float64
    attrs: pd.DataFrame  # W rows aligned with well_ids: well_id and the fixed attributes of dim_well
    # Attributes that change by month as integer codes into `categories`: the last value reported up
    # to that month (forward filled, never a later one), -1 before the first report.
    period_codes: dict[str, np.ndarray] = field(default_factory=dict)
    categories: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Optional fracture features (RF21, D15): feature name -> (W, T) array of what is known at each month; None in the base model.
    fracture: dict[str, np.ndarray] | None = None


def days_in_months(period_index: np.ndarray) -> np.ndarray:
    """Calendar days of each month given as ``year * 12 + month - 1``."""
    return np.array([calendar.monthrange(int(i) // 12, int(i) % 12 + 1)[1] for i in period_index], dtype=np.int64)


def assemble_panel(
    well_ids: np.ndarray,
    period_index: np.ndarray,
    volume: dict[str, np.ndarray],
    water_volume: np.ndarray,
    attrs: pd.DataFrame,
    period_codes: dict[str, np.ndarray] | None = None,
    categories: dict[str, tuple[str, ...]] | None = None,
) -> SeriesPanel:
    """Build a panel from dense volume arrays, deriving the days of each month and the rates.

    ``build_panel`` uses it after reading the warehouse; tests use it to build synthetic panels.
    """
    days = days_in_months(period_index)
    return SeriesPanel(
        well_ids=np.asarray(well_ids, dtype=np.int64),
        period_index=np.asarray(period_index, dtype=np.int64),
        days_in_month=days,
        volume={fluid: np.asarray(volume[fluid], dtype=np.float64) for fluid in FLUIDS},
        rate={fluid: np.asarray(volume[fluid], dtype=np.float64) / days[None, :] for fluid in FLUIDS},
        water_rate=np.asarray(water_volume, dtype=np.float64) / days[None, :],
        attrs=attrs,
        period_codes=period_codes or {},
        categories=categories or {},
    )


def _forward_fill_codes(codes: np.ndarray) -> np.ndarray:
    """Replace -1 by the last known code of the same row (-1 stays only before the first one)."""
    last_valid = np.where(codes >= 0, np.arange(codes.shape[1])[None, :], 0)
    np.maximum.accumulate(last_valid, axis=1, out=last_valid)
    return np.take_along_axis(codes, last_valid, axis=1)


def build_panel(conn: sqlite3.Connection, well_sample: int = 0, seed: int = 42) -> SeriesPanel:
    """Read ``stg_monthly_production`` and ``dim_well`` into a dense panel.

    ``well_sample > 0`` keeps that many wells, a fixed subset for a given `seed` (for development).
    """
    stg = pd.read_sql_query(
        "SELECT well_id, period_index, oil_m3, gas_thousand_m3, water_m3, company_code, well_type, extraction_method "
        "FROM stg_monthly_production ORDER BY well_id, period_index",
        conn,
    )
    if stg.empty:
        raise ValueError("the warehouse has no production rows: load a validated publication first")
    # The months span the whole warehouse, not the sample, so a sample has the same columns as the full panel.
    first, last = int(stg["period_index"].min()), int(stg["period_index"].max())
    well_ids = np.sort(stg["well_id"].unique()).astype(np.int64)
    if 0 < well_sample < len(well_ids):
        rng = np.random.default_rng(seed)
        well_ids = np.sort(rng.choice(well_ids, size=well_sample, replace=False))
        stg = stg[stg["well_id"].isin(well_ids)]
    period_index = np.arange(first, last + 1, dtype=np.int64)
    rows = np.searchsorted(well_ids, stg["well_id"].to_numpy())
    cols = stg["period_index"].to_numpy() - first

    def dense(values: pd.Series) -> np.ndarray:
        out = np.full((len(well_ids), len(period_index)), np.nan)
        out[rows, cols] = values.to_numpy(dtype=np.float64, na_value=np.nan)
        return out

    codes: dict[str, np.ndarray] = {}
    categories: dict[str, tuple[str, ...]] = {}
    for name, column in CATEGORY_COLUMNS.items():
        categorical = pd.Categorical(stg[column])
        grid = np.full((len(well_ids), len(period_index)), -1, dtype=np.int16)
        grid[rows, cols] = categorical.codes
        codes[name] = _forward_fill_codes(grid)
        categories[name] = tuple(str(c) for c in categorical.categories)

    dim = pd.read_sql_query(f"SELECT well_key AS well_id, {', '.join(ATTRIBUTE_COLUMNS)} FROM dim_well", conn)
    attrs = dim.set_index("well_id").reindex(well_ids).rename_axis("well_id").reset_index()
    return assemble_panel(
        well_ids,
        period_index,
        {fluid: dense(stg[VOLUME_COLUMN[fluid]]) for fluid in FLUIDS},
        dense(stg["water_m3"]),
        attrs,
        codes,
        categories,
    )


def column_of(panel: SeriesPanel, period_index: int) -> int:
    """Column of a month in the panel arrays."""
    col = int(period_index) - int(panel.period_index[0])
    if not 0 <= col < len(panel.period_index):
        raise ValueError(f"period index {period_index} is outside the panel ({panel.period_index[0]} to {panel.period_index[-1]})")
    return col


# --- rules of one series, at an origin column --------------------------------------------------------


def peak_column(rate_row: np.ndarray, upto: int) -> int | None:
    """Column of the highest positive rate among the columns ``0..upto`` (the first one on a tie).

    A later, higher peak (a restimulation) replaces an earlier one: the post-peak segment restarts.
    """
    if upto < 0:
        return None
    window = rate_row[: upto + 1]
    positive = np.where(window > 0, window, -np.inf)
    col = int(np.argmax(positive))
    return col if positive[col] > 0 else None


def post_peak_points(rate_row: np.ndarray, upto: int) -> tuple[np.ndarray, np.ndarray]:
    """``(t, rate)`` of the positive months from the peak to `upto`; ``t`` counts calendar months from the peak.

    Months in zero or without a row are left out of the points, but the clock keeps running (D06).
    """
    peak = peak_column(rate_row, upto)
    if peak is None:
        return np.empty(0), np.empty(0)
    window = rate_row[peak : upto + 1]
    positive = window > 0
    return np.flatnonzero(positive).astype(np.float64), window[positive]


def segment_at(rate_row: np.ndarray, upto: int, min_points: int) -> Segment:
    """``eligible`` (active, at least `min_points` positive months since the peak), ``young`` or ``inactive``."""
    start = max(0, upto - ACTIVITY_MONTHS + 1)
    if upto < 0 or not np.any(rate_row[start : upto + 1] > 0):
        return "inactive"
    t, _ = post_peak_points(rate_row, upto)
    return "eligible" if t.size >= min_points else "young"


def age_bucket(n_post_peak: int, young_below: int = YOUNG_BELOW) -> str:
    """Age band of a series by its number of positive months since the peak."""
    if n_post_peak < young_below:
        return "young"
    if n_post_peak < 12:
        return "06-11"
    if n_post_peak < 24:
        return "12-23"
    if n_post_peak < 60:
        return "24-59"
    return "60+"
