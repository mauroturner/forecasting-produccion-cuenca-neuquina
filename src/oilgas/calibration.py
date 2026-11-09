"""Empirical P10/P90 bands for the point methods, from errors already realized (RF12, D09).

The error of a point forecast is measured in log scale of the daily rate,
``e = ln((actual + eps) / (p50 + eps))``. The band at an origin ``o`` for horizon ``h`` comes from the
quantiles of the errors of the ``window`` most recent origins ``o'`` whose target month is already
known (``o' + h <= o``), per (method, fluid, horizon, age bucket); a cell with fewer than
``min_calibration_samples`` errors borrows the quantiles of its (method, fluid, horizon). The median
forecast is never corrected, and the band never crosses it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from oilgas.config import BacktestConfig

LOW_QUANTILE = 0.1
HIGH_QUANTILE = 0.9
ANY_BUCKET = "*"  # age bucket of the rows that hold the (method, fluid, horizon) quantiles
CELL = ["method", "fluid", "horizon"]
BAND_COLUMNS = [*CELL, "age_bucket", "q10", "q90", "n", "level"]


def log_error(actual_rate: np.ndarray, p50_rate: np.ndarray, eps: float) -> np.ndarray:
    """``ln((actual + eps) / (p50 + eps))`` for daily rates; positive when the forecast was too low."""
    return np.log((np.asarray(actual_rate, dtype=np.float64) + eps) / (np.asarray(p50_rate, dtype=np.float64) + eps))


def calibration_pool(errors: pd.DataFrame, origin: int, horizon: int, window: int) -> pd.DataFrame:
    """Errors of `horizon` made at origins ``o'`` in ``[origin - horizon - window + 1, origin - horizon]``.

    Their target month ``o' + horizon`` is never after `origin`. `errors` needs ``origin``, ``horizon`` and ``error``.
    """
    o = errors["origin"]
    keep = (errors["horizon"] == horizon) & (o + horizon <= origin) & (o >= origin - horizon - (window - 1))
    return errors[keep]


def _quantiles(pool: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    grouped = pool.groupby(by, observed=True)["error"]
    out = grouped.quantile([LOW_QUANTILE, HIGH_QUANTILE]).unstack()
    out.columns = ["q10", "q90"]
    out["n"] = grouped.size()
    return out.reset_index()


def band_quantiles(errors: pd.DataFrame, origin: int, cfg: BacktestConfig) -> pd.DataFrame:
    """Quantiles of the realized errors available at `origin`, per (method, fluid, horizon, age bucket).

    `errors` has ``method, fluid, horizon, origin, age_bucket, error``. The result has one row per
    cell with ``q10, q90`` (``level`` ``cell`` or ``method`` when it borrowed), the cell's own sample
    size ``n``, and one row per (method, fluid, horizon) with ``age_bucket == "*"``.
    """
    window = cfg.calibration_window_origins
    horizons = errors["horizon"].unique()
    if len(horizons) == 0:
        return pd.DataFrame(columns=BAND_COLUMNS)
    # A coarse cut first, so that the per-horizon filters work on a fraction of a large frame.
    o = errors["origin"]
    recent = errors[(o < origin) & (o >= origin - int(horizons.max()) - (window - 1))]
    pools = [calibration_pool(recent, origin, int(h), window) for h in sorted(horizons)]
    pool = pd.concat(pools, ignore_index=True) if pools else recent.iloc[0:0]
    if pool.empty:
        return pd.DataFrame(columns=BAND_COLUMNS)
    method_level = _quantiles(pool, CELL)
    cells = _quantiles(pool, [*CELL, "age_bucket"])
    borrowed = cells["n"] < cfg.min_calibration_samples
    fallback = cells[CELL].merge(method_level[[*CELL, "q10", "q90"]], on=CELL, how="left")
    cells["level"] = np.where(borrowed, "method", "cell")
    cells.loc[borrowed, ["q10", "q90"]] = fallback.loc[borrowed, ["q10", "q90"]].to_numpy()
    method_level["age_bucket"] = ANY_BUCKET
    method_level["level"] = "method"
    return pd.concat([cells, method_level], ignore_index=True)[BAND_COLUMNS]


def apply_bands(p50_rate: np.ndarray, q10: np.ndarray, q90: np.ndarray, eps: float) -> tuple[np.ndarray, np.ndarray]:
    """P10 and P90 daily rates from the median rate and the error quantiles.

    ``P10 = max((p50 + eps) exp(q10) - eps, 0)`` and likewise for P90, with the quantiles clipped to
    ``q10 <= 0 <= q90`` so that P10 <= P50 <= P90 always holds (a method that was biased in every
    recent error has a band that starts at its median). NaN quantiles give NaN bands.
    """
    median = np.asarray(p50_rate, dtype=np.float64)
    base = median + eps
    # The final min / max make the order exact even where adding and subtracting eps rounds.
    p10 = np.minimum(np.maximum(base * np.exp(np.minimum(q10, 0.0)) - eps, 0.0), median)
    p90 = np.maximum(np.maximum(base * np.exp(np.maximum(q90, 0.0)) - eps, 0.0), median)
    return p10, p90
