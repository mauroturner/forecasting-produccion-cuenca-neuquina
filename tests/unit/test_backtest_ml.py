"""The machine-learning model inside the walk-forward backtest: pairs, retraining cadence, no leakage (AC11)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from oilgas import backtest
from oilgas.backtest import (
    BacktestPlan,
    add_empirical_bands,
    evaluation_pairs,
    plan_origins,
    run_ml,
    run_point_methods,
)
from oilgas.config import PipelineConfig, load_config
from oilgas.series import SeriesPanel, column_of
from tests.fixtures.synthetic_panel import perturb_after, synthetic_panel

BASE = load_config()
KEYS = ["fluid", "well_id", "origin", "horizon"]


def cfg_for(**ml) -> PipelineConfig:
    return dataclasses.replace(
        BASE,
        backtest=dataclasses.replace(BASE.backtest, n_workers=1),
        ml=dataclasses.replace(BASE.ml, max_iter=8, min_samples_leaf=10, max_train_rows=2000, train_window_months=18, retrain_every=3, **ml),
    )


@pytest.fixture(scope="module")
def panel() -> SeriesPanel:
    return synthetic_panel(n_wells=30, n_months=48, seed=3, young_wells=4)


@pytest.fixture(scope="module")
def plan(panel) -> BacktestPlan:
    return plan_origins(int(panel.period_index[-1]), dataclasses.replace(BASE.backtest, n_eval_origins=7, n_warmup_origins=2))


@pytest.fixture(scope="module")
def ml(panel, plan) -> pd.DataFrame:
    return run_ml(panel, plan, cfg_for())


def test_the_ml_frame_has_the_shape_of_the_point_frame(ml: pd.DataFrame, plan: BacktestPlan) -> None:
    assert list(ml.columns) == backtest.FRAME_COLUMNS
    assert set(ml["method"].astype(str)) == {"ml_hgb"} and ml["method"].cat.categories.tolist() == list(backtest.METHOD_CATEGORIES)
    assert set(ml["origin"]) <= set(plan.eval_origins)  # the model runs on the evaluation origins only
    assert set(ml["horizon"]) == {1, 3, 6}  # 1, 3, 6 and 12 where the target exists
    assert set(ml["segment"].astype(str)) == {"eligible", "young"}
    assert ml[["p10", "p50", "p90", "actual"]].notna().all().all()
    assert (ml["p10"] <= ml["p50"]).all() and (ml["p50"] <= ml["p90"]).all() and (ml["p10"] >= 0).all()
    assert (ml["fit_status"] == "ok").all()


def test_the_ml_forecasts_exactly_the_pairs_the_baselines_do(ml: pd.DataFrame, panel: SeriesPanel, plan: BacktestPlan) -> None:
    point = run_point_methods(panel, plan, cfg_for(), methods=("naive_last",))
    point = point[point["origin"].isin(plan.eval_origins) & point["horizon"].isin(BASE.backtest.eval_horizons)]
    a = point.set_index(KEYS).sort_index()
    b = ml.set_index(KEYS).sort_index()
    assert a.index.equals(b.index)
    for column in ("segment", "age_bucket", "n_post_peak", "target_days", "actual"):
        assert (a[column].astype(str) == b[column].astype(str)).all() or np.array_equal(a[column].to_numpy(), b[column].to_numpy())


def test_the_frame_is_sorted(ml: pd.DataFrame) -> None:
    order = np.lexsort((ml["horizon"], ml["origin"], ml["well_id"], ml["fluid"].cat.codes))
    assert (order == np.arange(len(ml))).all()


def test_the_model_is_retrained_every_third_evaluation_origin_with_data_up_to_that_origin(
    monkeypatch: pytest.MonkeyPatch, panel: SeriesPanel, plan: BacktestPlan, ml: pd.DataFrame
) -> None:
    trained_at: list[tuple[str, int, int]] = []
    used: list[tuple[object, int]] = []  # (the models object, rows predicted) in call order; kept alive on purpose
    real_training, real_predict = backtest.training_examples, backtest.predict_volumes

    def spy_training(p, fluid, horizon, origin_col, cfg, eps):
        trained_at.append((fluid, horizon, origin_col))
        return real_training(p, fluid, horizon, origin_col, cfg, eps)

    def spy_predict(models, X, base, days, eps):
        used.append((models, len(X)))
        return real_predict(models, X, base, days, eps)

    monkeypatch.setattr(backtest, "training_examples", spy_training)
    monkeypatch.setattr(backtest, "predict_volumes", spy_predict)
    frame = run_ml(panel, plan, cfg_for())
    c = [column_of(panel, o) for o in plan.eval_origins]
    # The plan ends 7 months before the data does: horizon 1 has a target at all 7 origins, 3 at the
    # first 5, 6 at the first 2 and 12 at none. A model is trained when an origin of its block needs it,
    # at the origin that starts the block (indices 0, 3 and 6 of the evaluation origins).
    expected = {1: [c[0], c[3], c[6]], 3: [c[0], c[3]], 6: [c[0]]}
    for fluid in ("oil", "gas"):
        for horizon, origins in expected.items():
            assert [col for f, h, col in trained_at if (f, h) == (fluid, horizon)] == origins
        assert not [1 for f, h, _ in trained_at if (f, h) == (fluid, 12)]
    assert len(trained_at) == 2 * sum(len(v) for v in expected.values())
    # Between retrainings the same models serve three consecutive origins: A A A B B B C, A A A B B, A A.
    sizes = [7, 5, 2] * 2
    start = 0
    for size in sizes:
        chunk = [m for m, _ in used[start : start + size]]
        start += size
        for i, m in enumerate(chunk):
            assert m is chunk[(i // 3) * 3]
        starts = [chunk[i] for i in range(0, size, 3)]
        assert all(starts[i] is not starts[j] for i in range(len(starts)) for j in range(i))
    assert start == len(used) and len(frame) == sum(n for _, n in used)
    pd.testing.assert_frame_equal(frame, ml)  # the same run again gives the same forecasts


@pytest.mark.parametrize("position", [2, 3])  # an origin that reuses a model, and one that retrains
def test_scrambling_everything_after_an_origin_changes_no_ml_forecast_made_at_or_before_it(
    panel: SeriesPanel, plan: BacktestPlan, ml: pd.DataFrame, position: int
) -> None:
    origin = plan.eval_origins[position]
    base = ml
    changed = run_ml(perturb_after(panel, column_of(panel, origin)), plan, cfg_for())
    a = base[base["origin"] <= origin].set_index(KEYS).sort_index()
    b = changed[changed["origin"] <= origin].set_index(KEYS).sort_index()
    assert len(a) > 100 and a.index.equals(b.index)
    for column in ("p10", "p50", "p90"):
        np.testing.assert_array_equal(a[column].to_numpy(), b[column].to_numpy())
    assert not np.array_equal(a["actual"].to_numpy(), b["actual"].to_numpy())  # the targets did move
    later_a = base[base["origin"] > origin].set_index(KEYS).sort_index()
    later_b = changed[changed["origin"] > origin].set_index(KEYS).sort_index()
    assert len(later_a) and later_a.index.equals(later_b.index)
    assert not np.array_equal(later_a["p50"].to_numpy(), later_b["p50"].to_numpy())  # later origins do see the new data


def test_evaluating_all_six_methods_on_the_same_pairs(panel: SeriesPanel, plan: BacktestPlan, ml: pd.DataFrame) -> None:
    cfg = cfg_for()
    point = add_empirical_bands(run_point_methods(panel, plan, cfg), plan, cfg.backtest)
    both = pd.concat([point, ml], ignore_index=True)
    evaluation = evaluation_pairs(both, plan, cfg.backtest)
    eligible = evaluation[evaluation["segment"] == "eligible"]
    counts = eligible.groupby(eligible["method"].astype(str)).size()
    assert set(counts.index) == set(backtest.METHOD_CATEGORIES) and counts.nunique() == 1
    young = evaluation[evaluation["segment"] == "young"]
    assert set(young["method"].astype(str)) == {"naive_last", "naive_mean3", "ml_hgb"}
    assert young.groupby(young["method"].astype(str)).size().nunique() == 1
