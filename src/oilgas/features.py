"""Features and training examples of the machine-learning model (RF10, plan section 9.3, D08).

Every feature at column ``t`` uses only columns ``<= t`` of the panel. The model predicts
``y = ln((rate[t + h] + eps) / (m3[t] + eps))``, with ``m3`` the mean daily rate of the last three
months; the training examples for an origin ``o`` are the (series, month ``t``) pairs that are active
at ``t``, have a row at ``t + h`` and have ``t + h`` within the last ``train_window_months`` months up
to and including ``o``. Windows are clipped at the start of the panel, and months without a row are
skipped when averaging.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from oilgas.config import MLConfig
from oilgas.fracture import FRACTURE_FEATURES, fracture_at
from oilgas.series import ACTIVITY_MONTHS, SeriesPanel

LAGS = 6
NUMERIC_FEATURES = (
    *(f"log_rate_lag{k}" for k in range(LAGS)),
    "log_mean3", "log_mean6", "decline_3", "decline_6", "log_peak_rate", "ratio_to_peak", "months_since_first",
    "months_since_peak", "zero_months_last6", "log_cum_oil", "log_cum_gas", "log_gor", "water_cut_mean3",
    "target_month", "lon", "lat", "depth_m",
)
CATEGORICAL_FEATURES = ("sub_resource_type", "formation", "well_type_at_t", "extraction_method_at_t", "operator_at_t")
FEATURE_COLUMNS = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
OTHER = "other"  # label of a category that is missing or was not kept as a level
# Features of the panel that change by month: feature name -> name in SeriesPanel.period_codes.
PERIOD_CATEGORIES = {"well_type_at_t": "well_type", "extraction_method_at_t": "extraction_method", "operator_at_t": "operator"}


def _rows(panel: SeriesPanel, rows: np.ndarray | None) -> np.ndarray:
    return np.arange(len(panel.well_ids)) if rows is None else np.asarray(rows, dtype=np.int64)


def _mean_cols(values: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Mean over columns ``lo..hi`` (clipped to the array), ignoring months without a row; NaN if there is none."""
    lo, hi = max(lo, 0), min(hi, values.shape[1] - 1)
    if hi < lo:
        return np.full(values.shape[0], np.nan)
    block = values[:, lo : hi + 1]
    present = ~np.isnan(block)
    count = present.sum(axis=1)
    total = np.where(present, block, 0.0).sum(axis=1)
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def _log_ratio(a: np.ndarray, b: np.ndarray, eps: float) -> np.ndarray:
    return np.log((a + eps) / (b + eps))


def base_rate(panel: SeriesPanel, fluid: str, col: int, rows: np.ndarray | None = None) -> np.ndarray:
    """Mean daily rate of the three months up to `col` (``m3``): the level a forecast is expressed against."""
    return _mean_cols(panel.rate[fluid][_rows(panel, rows)], col - ACTIVITY_MONTHS + 1, col)


def _labels(codes: np.ndarray, categories: tuple[str, ...]) -> np.ndarray:
    table = np.array([*categories, OTHER], dtype=object)
    return table[np.where(codes >= 0, codes, len(categories))]  # code -1 indexes the last item: "other"


def features_at(panel: SeriesPanel, fluid: str, col: int, rows: np.ndarray | None = None, horizon: int = 1, eps: float = 0.1) -> pd.DataFrame:
    """Feature table of the series `rows` (all by default) as known at column `col`, for a target `horizon` months later.

    Numeric columns are floats (NaN where the history is too short); categorical ones are labels, the
    last value reported up to `col` for those that change by month, ``"other"`` when unknown.
    """
    idx = _rows(panel, rows)
    rate = panel.rate[fluid][idx]
    n = len(idx)
    out: dict[str, np.ndarray] = {}
    for k in range(LAGS):
        lag = rate[:, col - k] if col - k >= 0 else np.full(n, np.nan)
        out[f"log_rate_lag{k}"] = np.log1p(lag)
    m3 = _mean_cols(rate, col - 2, col)
    m6 = _mean_cols(rate, col - 5, col)
    out["log_mean3"], out["log_mean6"] = np.log1p(m3), np.log1p(m6)
    out["decline_3"] = _log_ratio(m3, _mean_cols(rate, col - 5, col - 3), eps)
    out["decline_6"] = _log_ratio(m3, _mean_cols(rate, col - 8, col - 6), eps)

    history = rate[:, : col + 1]
    positive = history > 0
    peak_values = np.where(positive, history, -np.inf)
    peak_rate = peak_values.max(axis=1)
    produced = np.isfinite(peak_rate)
    peak_col = peak_values.argmax(axis=1)
    first_col = positive.argmax(axis=1)
    out["log_peak_rate"] = np.where(produced, np.log1p(np.where(produced, peak_rate, 0.0)), np.nan)
    out["ratio_to_peak"] = np.where(produced, _log_ratio(m3, np.where(produced, peak_rate, 0.0), eps), np.nan)
    out["months_since_first"] = np.where(produced, col - first_col, np.nan)
    out["months_since_peak"] = np.where(produced, col - peak_col, np.nan)
    out["zero_months_last6"] = (rate[:, max(0, col - 5) : col + 1] == 0).sum(axis=1).astype(np.float64)

    for name, key in (("log_cum_oil", "oil"), ("log_cum_gas", "gas")):
        out[name] = np.log1p(np.nansum(panel.volume[key][idx, : col + 1], axis=1))
    out["log_gor"] = _log_ratio(_mean_cols(panel.rate["gas"][idx], col - 2, col), _mean_cols(panel.rate["oil"][idx], col - 2, col), eps)
    water = _mean_cols(panel.water_rate[idx], col - 2, col)
    oil = _mean_cols(panel.rate["oil"][idx], col - 2, col)
    total = oil + water
    out["water_cut_mean3"] = np.where(total > 0, water / np.where(total > 0, total, 1.0), np.nan)
    out["target_month"] = np.full(n, float((int(panel.period_index[col]) + horizon) % 12 + 1))
    for name in ("lon", "lat", "depth_m"):
        out[name] = panel.attrs[name].to_numpy(dtype=np.float64)[idx]

    frame = pd.DataFrame(out)
    attrs = panel.attrs.iloc[idx]
    frame["sub_resource_type"] = attrs["sub_resource_type"].fillna(OTHER).to_numpy(dtype=object)
    frame["formation"] = attrs["formation_name"].fillna(OTHER).to_numpy(dtype=object)
    for feature, key in PERIOD_CATEGORIES.items():
        frame[feature] = _labels(panel.period_codes[key][idx, col], panel.categories[key])
    if panel.fracture is not None:  # the ablation: only what is known at `col` (fractures ended by then)
        for name, values in fracture_at(panel, col, idx).items():
            frame[name] = values
        return frame[[*FEATURE_COLUMNS, *FRACTURE_FEATURES]].reset_index(drop=True)
    return frame[FEATURE_COLUMNS].reset_index(drop=True)


def training_target_range(origin_col: int, horizon: int, cfg: MLConfig) -> tuple[int, int]:
    """First and last month ``t`` of the training examples: their targets ``t + h`` fill the window ending at the origin."""
    return origin_col - (cfg.train_window_months - 1) - horizon, origin_col - horizon


def training_examples(panel: SeriesPanel, fluid: str, horizon: int, origin_col: int, cfg: MLConfig, eps: float) -> tuple[pd.DataFrame, np.ndarray]:
    """``(X, y)`` for the origin: every active (series, month) with a known target not after `origin_col`.

    Young series are included. A set larger than ``cfg.max_train_rows`` is sampled with ``cfg.seed``.
    """
    first, last = training_target_range(origin_col, horizon, cfg)
    rate = panel.rate[fluid]
    tables, targets = [], []
    for t in range(max(first, 0), last + 1):
        active = np.any(rate[:, max(0, t - ACTIVITY_MONTHS + 1) : t + 1] > 0, axis=1)
        known = ~np.isnan(rate[:, t + horizon])
        rows = np.flatnonzero(active & known)
        if rows.size == 0:
            continue
        tables.append(features_at(panel, fluid, t, rows, horizon, eps))
        targets.append(_log_ratio(rate[rows, t + horizon], base_rate(panel, fluid, t, rows), eps))
    if not tables:
        return pd.DataFrame(columns=FEATURE_COLUMNS), np.empty(0)
    X, y = pd.concat(tables, ignore_index=True), np.concatenate(targets)
    if len(X) > cfg.max_train_rows:
        keep = np.sort(np.random.default_rng(cfg.seed).choice(len(X), size=cfg.max_train_rows, replace=False))
        X, y = X.iloc[keep].reset_index(drop=True), y[keep]
    return X, y

