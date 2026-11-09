"""Quantile gradient boosting: configuration, learning, categories, ordering of the quantiles (RF10, D08)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from oilgas.ml import QuantileModels, fit_quantile_models, predict_volumes

EPS = 0.1
ML = load_config().ml
COLUMNS = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]


def feature_frame(n: int, seed: int = 0, operators=("YPF", "VISTA", "PAE")) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({name: rng.normal(size=n) for name in NUMERIC_FEATURES})
    frame["sub_resource_type"] = rng.choice(["SHALE", "TIGHT"], size=n)
    frame["formation"] = rng.choice(["vaca muerta", "lajas"], size=n)
    frame["well_type_at_t"] = "Petrolífero"
    frame["extraction_method_at_t"] = rng.choice(["Gas Lift", "Plunger Lift"], size=n)
    frame["operator_at_t"] = rng.choice(list(operators), size=n)
    return frame[COLUMNS]


def small_cfg(**changes):
    return dataclasses.replace(ML, max_iter=60, min_samples_leaf=20, **changes)


def test_one_model_per_quantile_with_the_preregistered_hyperparameters() -> None:
    X = feature_frame(400)
    y = X["log_mean3"].to_numpy() + np.random.default_rng(1).normal(size=400)
    models = fit_quantile_models(X, y, ML)
    assert isinstance(models, QuantileModels) and sorted(models) == [0.1, 0.5, 0.9]
    for alpha, model in models.items():
        params = model.get_params()
        assert params["loss"] == "quantile" and params["quantile"] == alpha
        assert (params["max_iter"], params["learning_rate"], params["max_leaf_nodes"]) == (250, 0.06, 31)
        assert (params["min_samples_leaf"], params["l2_regularization"], params["random_state"]) == (200, 1.0, 42)
        assert params["early_stopping"] is False and params["categorical_features"] == "from_dtype"
        assert model.is_categorical_.sum() == len(CATEGORICAL_FEATURES)


def test_each_model_predicts_its_own_quantile() -> None:
    rng = np.random.default_rng(3)
    X = feature_frame(6000, seed=3)
    y = 2.0 * X["log_mean3"].to_numpy() + np.where(X["operator_at_t"] == "YPF", 1.0, 0.0) + rng.normal(size=6000)
    models = fit_quantile_models(X, y, small_cfg())
    share_below = {alpha: float(np.mean(y <= model.predict(models.cast(X)))) for alpha, model in models.items()}
    for alpha, share in share_below.items():
        assert share == pytest.approx(alpha, abs=0.05), (alpha, share)
    # The categorical column is used: YPF wells are predicted one unit higher at the median, other things equal.
    ypf = X["operator_at_t"] == "YPF"
    median = models[0.5].predict(models.cast(X))
    from_numeric = 2.0 * (X.loc[ypf, "log_mean3"].mean() - X.loc[~ypf, "log_mean3"].mean())
    assert median[ypf].mean() - median[~ypf].mean() == pytest.approx(1.0 + from_numeric, abs=0.3)


def test_levels_keep_the_most_frequent_values_and_everything_else_is_other() -> None:
    operators = [f"OP{i:02d}" for i in range(20)]
    X = feature_frame(2000, operators=operators)
    X["operator_at_t"] = np.repeat(operators, 100)[:2000]
    X.loc[100:249, "operator_at_t"] = "OP00"  # 250 rows: clearly the most frequent
    cfg = small_cfg(top_operators=5)
    models = fit_quantile_models(X, np.zeros(2000), cfg)
    levels = models.levels["operator_at_t"]
    assert len(levels) == 5 and levels[0] == "OP00"
    assert set(levels) <= set(operators)
    assert models.levels["sub_resource_type"] == ("SHALE", "TIGHT")
    assert len(models.levels["formation"]) <= cfg.top_formations
    cast = models.cast(X)
    assert set(cast["operator_at_t"].astype(str)) == set(levels) | {"other"}
    assert cast["operator_at_t"].dtype.categories.tolist() == [*levels, "other"]


def test_a_level_never_seen_in_training_is_treated_as_other() -> None:
    X = feature_frame(1500)
    y = np.where(X["operator_at_t"] == "PAE", 5.0, 0.0) + np.random.default_rng(2).normal(size=1500) * 0.1
    cfg = small_cfg(top_operators=2)  # PAE is the third and falls in "other" in training
    models = fit_quantile_models(X, y, cfg)
    probe = feature_frame(40, seed=9)
    unseen, other = probe.copy(), probe.copy()
    unseen["operator_at_t"], other["operator_at_t"] = "NEVER_SEEN", "other"
    base = np.ones(40)
    days = np.full(40, 30.0)
    np.testing.assert_array_equal(predict_volumes(models, unseen, base, days, EPS), predict_volumes(models, other, base, days, EPS))


def test_fitting_twice_gives_the_same_models() -> None:
    X = feature_frame(800, seed=5)
    y = X["decline_3"].to_numpy() * 0.5
    a, b = fit_quantile_models(X, y, small_cfg()), fit_quantile_models(X, y, small_cfg())
    probe = feature_frame(30, seed=6)
    for alpha in a:
        np.testing.assert_array_equal(a[alpha].predict(a.cast(probe)), b[alpha].predict(b.cast(probe)))


class Constant:
    """A stand-in model that always predicts one value."""

    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self.value)


def stub_models(low: float, mid: float, high: float) -> QuantileModels:
    models = QuantileModels({0.1: Constant(low), 0.5: Constant(mid), 0.9: Constant(high)})
    models.levels = {name: ("a",) for name in ("sub_resource_type", "formation", "well_type_at_t", "extraction_method_at_t", "operator_at_t")}
    return models


def test_predicted_volumes_undo_the_target_transformation_by_hand() -> None:
    X = feature_frame(2)
    out = predict_volumes(stub_models(-0.5, 0.0, 0.4), X, np.array([10.0, 0.0]), np.array([30.0, 31.0]), EPS)
    assert out.shape == (2, 3)
    expected = [[(10.1 * math.exp(q) - EPS) * 30 for q in (-0.5, 0.0, 0.4)], [(0.1 * math.exp(q) - EPS) * 31 for q in (-0.5, 0.0, 0.4)]]
    assert out[0].tolist() == pytest.approx(expected[0])
    assert out[1, 0] == 0.0  # 0.1 * exp(-0.5) - 0.1 < 0: a volume is never negative
    assert out[1, 1] == pytest.approx(0.0, abs=1e-9) and out[1, 2] == pytest.approx(expected[1][2])


def test_the_three_quantiles_are_sorted_even_when_the_models_cross() -> None:
    X = feature_frame(3)
    out = predict_volumes(stub_models(0.5, 0.0, -0.5), X, np.full(3, 10.0), np.full(3, 30.0), EPS)
    assert (out[:, 0] <= out[:, 1]).all() and (out[:, 1] <= out[:, 2]).all()
    straight = predict_volumes(stub_models(-0.5, 0.0, 0.5), X, np.full(3, 10.0), np.full(3, 30.0), EPS)
    np.testing.assert_array_equal(out, straight)


def test_a_real_fit_gives_ordered_quantiles_for_every_row() -> None:
    rng = np.random.default_rng(8)
    X = feature_frame(3000, seed=8)
    y = X["log_mean3"].to_numpy() + rng.normal(size=3000)
    models = fit_quantile_models(X, y, small_cfg())
    out = predict_volumes(models, feature_frame(500, seed=10), np.full(500, 20.0), np.full(500, 31.0), EPS)
    assert (out >= 0).all() and (np.diff(out, axis=1) >= 0).all()
