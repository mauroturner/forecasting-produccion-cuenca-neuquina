"""Forecast metrics on volumes in the fluid's own unit; fluids are never mixed (RF13, plan section 11).

WAPE is the relative metric (MAPE breaks with the 20 % of months in zero). A metric of nothing, or
relative to a total of zero, is NaN rather than an exception. ``additive_components`` keeps only
sums, so any aggregation (a DAX measure under any filter) is a ratio of sums.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

QUANTILES = (0.1, 0.5, 0.9)
COMPONENT_COLUMNS = (
    "n", "sum_actual", "sum_p10", "sum_p50", "sum_p90", "sum_abs_error", "sum_sq_error", "sum_error", "n_covered", "sum_pinball",
)


def _arrays(y, yhat) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(y, dtype=np.float64), np.asarray(yhat, dtype=np.float64)


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else float("nan")


def mae(y, yhat) -> float:
    y, yhat = _arrays(y, yhat)
    return float(np.abs(y - yhat).mean()) if y.size else float("nan")


def rmse(y, yhat) -> float:
    y, yhat = _arrays(y, yhat)
    return float(np.sqrt(((y - yhat) ** 2).mean())) if y.size else float("nan")


def wape(y, yhat) -> float:
    """Sum of absolute errors over the sum of actuals."""
    y, yhat = _arrays(y, yhat)
    return _ratio(np.abs(y - yhat).sum(), y.sum()) if y.size else float("nan")


def bias(y, yhat) -> float:
    """Sum of (forecast - actual) over the sum of actuals: positive means over-forecasting."""
    y, yhat = _arrays(y, yhat)
    return _ratio((yhat - y).sum(), y.sum()) if y.size else float("nan")


def coverage(y, lo, hi) -> float:
    """Share of actuals inside ``[lo, hi]``, edges included."""
    y, lo = _arrays(y, lo)
    hi = np.asarray(hi, dtype=np.float64)
    return float(((lo <= y) & (y <= hi)).mean()) if y.size else float("nan")


def pinball(y, q, alpha: float) -> np.ndarray:
    """Pinball loss of the quantile forecast `q` at level `alpha`, per row."""
    u = np.asarray(y, dtype=np.float64) - np.asarray(q, dtype=np.float64)
    return np.maximum(alpha * u, (alpha - 1.0) * u)


def _pinball_sum(y, p10, p50, p90) -> np.ndarray:
    return pinball(y, p10, QUANTILES[0]) + pinball(y, p50, QUANTILES[1]) + pinball(y, p90, QUANTILES[2])


def scaled_pinball(y, p10, p50, p90) -> float:
    """Sum over rows and the three quantiles of the pinball loss, over the sum of actuals."""
    y = np.asarray(y, dtype=np.float64)
    return _ratio(_pinball_sum(y, p10, p50, p90).sum(), y.sum()) if y.size else float("nan")


def additive_components(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Sums per group of `by` from rows with ``actual, p10, p50, p90``: everything a metric needs.

    ``n`` rows, the sums of actual and of each quantile, of absolute, squared and signed error
    (forecast - actual) of P50, ``n_covered`` (actual inside P10-P90) and ``sum_pinball``.
    """
    y = frame["actual"].to_numpy(dtype=np.float64)
    p10, p50, p90 = (frame[c].to_numpy(dtype=np.float64) for c in ("p10", "p50", "p90"))
    work = frame[list(by)].copy()
    work["n"] = 1
    work["sum_actual"] = y
    work["sum_p10"], work["sum_p50"], work["sum_p90"] = p10, p50, p90
    work["sum_abs_error"] = np.abs(p50 - y)
    work["sum_sq_error"] = (p50 - y) ** 2
    work["sum_error"] = p50 - y
    work["n_covered"] = ((p10 <= y) & (y <= p90)).astype(np.int64)
    work["sum_pinball"] = _pinball_sum(y, p10, p50, p90)
    grouped = work.groupby(list(by), sort=True, observed=True, dropna=False)[list(COMPONENT_COLUMNS)].sum()
    return grouped.reset_index()


def share_beats(frame: pd.DataFrame, method: str, baseline: str, by: list[str] | tuple[str, ...] = ("fluid", "horizon")) -> pd.DataFrame:
    """Share of series on which `method` has a strictly lower MAE than `baseline`.

    `frame` is the long backtest frame (``fluid, well_id, origin, horizon, method, actual, p50``).
    The comparison is per series (fluid and well) inside each group of `by`, over the (origin, horizon)
    pairs that both methods have. Returns the `by` columns plus ``n_series``, ``n_beats`` and ``share``.
    """
    by = list(by)
    keys = [*dict.fromkeys(["fluid", "well_id", "origin", "horizon", *by])]
    rows = frame[frame["method"].isin([method, baseline])]
    err = rows[[*keys, "method"]].copy()
    err["abs_error"] = (rows["actual"] - rows["p50"]).abs().to_numpy(dtype=np.float64)
    wide = err.pivot_table(index=keys, columns="method", values="abs_error", aggfunc="first", observed=True)
    wide = wide.dropna(subset=[method, baseline]).reset_index()
    per_series = wide.groupby([*dict.fromkeys([*by, "fluid", "well_id"])], observed=True)[[method, baseline]].mean().reset_index()
    per_series["beats"] = per_series[method] < per_series[baseline]
    out = per_series.groupby(by, observed=True)["beats"].agg(n_series="size", n_beats="sum").reset_index()
    out["n_beats"] = out["n_beats"].astype(np.int64)
    out["share"] = out["n_beats"] / out["n_series"]
    return out
