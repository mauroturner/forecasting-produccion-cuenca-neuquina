"""Quantile gradient boosting for the daily rate ratio (RF10, plan section 9.3, decision D08).

One ``HistGradientBoostingRegressor`` with quantile loss per quantile (0.1, 0.5, 0.9), fixed
hyperparameters (no search, so the comparison with Arps is not tilted toward a tuned model). The
categorical features keep the most frequent values of the training data and map the rest, and any
value unseen at prediction time, to ``"other"``.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from oilgas.config import MLConfig
from oilgas.features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, OTHER


class QuantileModels(dict):
    """``{quantile: fitted model}`` plus the levels of each categorical feature the models were fitted with."""

    levels: dict[str, tuple[str, ...]]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.levels = {}

    def cast(self, X: pd.DataFrame) -> pd.DataFrame:
        """`X` with the feature columns in order and the categorical ones as categories of the fitted levels (+ "other")."""
        out = X[FEATURE_COLUMNS].copy()
        for name in CATEGORICAL_FEATURES:
            levels = self.levels[name]
            values = out[name].astype(object).where(out[name].isin(levels), OTHER)
            out[name] = pd.Categorical(values, categories=[*levels, OTHER])
        return out


def _levels(values: pd.Series, keep: int | None) -> tuple[str, ...]:
    """The `keep` most frequent values (ties by name), or all of them in alphabetical order if `keep` is None."""
    counts = Counter(v for v in values.astype(object) if v != OTHER and pd.notna(v))
    if keep is None:
        return tuple(sorted(counts))
    return tuple(name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:keep])


def fit_quantile_models(X: pd.DataFrame, y: np.ndarray, cfg: MLConfig) -> QuantileModels:
    """Fit one model per quantile of ``cfg.quantiles`` on the training examples ``(X, y)``."""
    models = QuantileModels()
    keep = {
        "sub_resource_type": None, "formation": cfg.top_formations, "well_type_at_t": None,
        "extraction_method_at_t": cfg.top_extraction_methods, "operator_at_t": cfg.top_operators,
    }
    models.levels = {name: _levels(X[name], keep[name]) for name in CATEGORICAL_FEATURES}
    cast = models.cast(X)
    for alpha in cfg.quantiles:
        models[alpha] = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=alpha,
            max_iter=cfg.max_iter,
            learning_rate=cfg.learning_rate,
            max_leaf_nodes=cfg.max_leaf_nodes,
            min_samples_leaf=cfg.min_samples_leaf,
            l2_regularization=cfg.l2_regularization,
            early_stopping=False,
            random_state=cfg.seed,
            categorical_features="from_dtype",
        ).fit(cast, y)
    return models


def predict_volumes(models: QuantileModels, X: pd.DataFrame, base_rate: np.ndarray, target_days: np.ndarray, eps: float) -> np.ndarray:
    """Volumes ``(n, 3)`` for the three quantiles, sorted per row so that P10 <= P50 <= P90.

    ``volume = max((base_rate + eps) * exp(y_hat) - eps, 0) * target_days``, undoing the target
    ``y = ln((rate + eps) / (base_rate + eps))``.
    """
    cast = models.cast(X)
    predictions = np.column_stack([models[alpha].predict(cast) for alpha in sorted(models)])
    rates = np.maximum((np.asarray(base_rate, dtype=np.float64)[:, None] + eps) * np.exp(predictions) - eps, 0.0)
    return np.sort(rates * np.asarray(target_days, dtype=np.float64)[:, None], axis=1)
