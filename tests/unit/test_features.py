"""Features and training examples of the machine-learning model: values by hand and no leakage (RF10, AC11)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.features import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    base_rate,
    features_at,
    training_examples,
    training_target_range,
)
from oilgas.series import SeriesPanel, assemble_panel, days_in_months
from tests.fixtures.synthetic_panel import FIRST_INDEX, perturb_after, synthetic_panel

EPS = 0.1
ML = load_config().ml
NAN = np.nan
OIL_A = [NAN, 10, 20, 16, 12, 8, 4, 2, 1, 0, 0.5, 0.25]  # peak 20 at column 2, a month in zero at column 9


def hand_panel() -> SeriesPanel:
    period_index = np.arange(FIRST_INDEX, FIRST_INDEX + 12)
    days = days_in_months(period_index)
    oil = np.array([OIL_A, [5.0] * 12], dtype=float) * days
    gas, water = 2 * oil, 0.5 * oil
    attrs = pd.DataFrame(
        {
            "well_id": [1, 2], "well_code": ["A", "B"], "province": "Neuquén",
            "formation_name": ["vaca muerta", "lajas"], "sub_resource_type": ["SHALE", "TIGHT"],
            "lon": [-69.5, -69.1], "lat": [-38.1, -38.2], "depth_m": [3500.0, NAN],
        }
    )
    codes = {
        "operator": np.array([[-1] + [0] * 11, [1] * 12], dtype=np.int16),
        "well_type": np.zeros((2, 12), dtype=np.int16),
        "extraction_method": np.array([[-1] + [2] * 11, [0] * 12], dtype=np.int16),
    }
    categories = {"operator": ("YPF", "VISTA"), "well_type": ("Petrolífero",), "extraction_method": ("Gas Lift", "Plunger Lift", "Surgencia Natural")}
    return assemble_panel(np.array([1, 2]), period_index, {"oil": oil, "gas": gas}, water, attrs, codes, categories)


def ln_ratio(a: float, b: float) -> float:
    return math.log((a + EPS) / (b + EPS))


def test_the_feature_lists_are_the_ones_of_the_plan() -> None:
    assert NUMERIC_FEATURES[:6] == tuple(f"log_rate_lag{k}" for k in range(6))
    assert set(NUMERIC_FEATURES[6:]) == {
        "log_mean3", "log_mean6", "decline_3", "decline_6", "log_peak_rate", "ratio_to_peak", "months_since_first",
        "months_since_peak", "zero_months_last6", "log_cum_oil", "log_cum_gas", "log_gor", "water_cut_mean3",
        "target_month", "lon", "lat", "depth_m",
    }
    assert CATEGORICAL_FEATURES == ("sub_resource_type", "formation", "well_type_at_t", "extraction_method_at_t", "operator_at_t")
    assert len(set(NUMERIC_FEATURES) | set(CATEGORICAL_FEATURES)) == len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES)


def test_numeric_features_of_a_well_in_decline_by_hand() -> None:
    panel = hand_panel()
    x = features_at(panel, "oil", 8, rows=np.array([0]), horizon=3)
    assert list(x.columns) == [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
    row = x.iloc[0]
    for k, rate in enumerate([1, 2, 4, 8, 12, 16]):
        assert row[f"log_rate_lag{k}"] == pytest.approx(math.log1p(rate))
    m3, m6 = 7 / 3, 43 / 6
    assert row["log_mean3"] == pytest.approx(math.log1p(m3)) and row["log_mean6"] == pytest.approx(math.log1p(m6))
    assert row["decline_3"] == pytest.approx(ln_ratio(m3, 12.0))  # against the mean of columns 3-5
    assert row["decline_6"] == pytest.approx(ln_ratio(m3, 15.0))  # against columns 0-2: the missing month is skipped
    assert row["log_peak_rate"] == pytest.approx(math.log1p(20)) and row["ratio_to_peak"] == pytest.approx(ln_ratio(m3, 20.0))
    assert row["months_since_first"] == 7 and row["months_since_peak"] == 6 and row["zero_months_last6"] == 0
    days = panel.days_in_month
    assert row["log_cum_oil"] == pytest.approx(math.log1p(float(np.nansum(panel.volume["oil"][0, :9]))))
    assert row["log_cum_gas"] == pytest.approx(math.log1p(float(np.nansum(panel.volume["gas"][0, :9]))))
    assert row["log_gor"] == pytest.approx(ln_ratio(2 * m3, m3))
    assert row["water_cut_mean3"] == pytest.approx(1 / 3)
    assert row["target_month"] == 12  # column 8 is September 2018, plus 3 months
    assert (row["lon"], row["lat"], row["depth_m"]) == (-69.5, -38.1, 3500.0)
    assert days[8] == 30


def test_categorical_features_are_labels_with_the_last_known_value() -> None:
    panel = hand_panel()
    x = features_at(panel, "oil", 8, horizon=1)
    a, b = x.iloc[0], x.iloc[1]
    assert (a["sub_resource_type"], a["formation"]) == ("SHALE", "vaca muerta")
    assert (a["well_type_at_t"], a["extraction_method_at_t"], a["operator_at_t"]) == ("Petrolífero", "Surgencia Natural", "YPF")
    assert (b["sub_resource_type"], b["formation"], b["operator_at_t"], b["extraction_method_at_t"]) == ("TIGHT", "lajas", "VISTA", "Gas Lift")
    assert pd.isna(b["depth_m"])
    before = features_at(panel, "oil", 0, horizon=1).iloc[0]  # nothing reported yet in column 0 for well A
    assert before["operator_at_t"] == "other" and before["extraction_method_at_t"] == "other"


def test_a_zero_month_counts_and_a_short_history_gives_missing_values_not_zeros() -> None:
    panel = hand_panel()
    late = features_at(panel, "oil", 10, rows=np.array([0]), horizon=1).iloc[0]
    assert late["zero_months_last6"] == 1 and late["log_rate_lag1"] == 0.0  # the zero at column 9
    early = features_at(panel, "oil", 2, rows=np.array([0]), horizon=1).iloc[0]
    assert math.isnan(early["log_rate_lag2"]) and math.isnan(early["log_rate_lag3"]) and math.isnan(early["decline_3"]) and math.isnan(early["decline_6"])
    assert early["log_rate_lag0"] == pytest.approx(math.log1p(20))
    assert early["log_mean6"] == pytest.approx(math.log1p(15.0))  # the months that exist
    assert early["months_since_first"] == 1 and early["months_since_peak"] == 0


def test_a_series_that_never_produced_has_no_peak_features() -> None:
    panel = hand_panel()
    x = features_at(panel, "oil", 0, rows=np.array([0]), horizon=1).iloc[0]
    for name in ("log_peak_rate", "ratio_to_peak", "months_since_first", "months_since_peak"):
        assert math.isnan(x[name]), name


def test_rows_select_wells_and_the_fluid_selects_the_rates() -> None:
    panel = hand_panel()
    full = features_at(panel, "oil", 8, horizon=2)
    one = features_at(panel, "oil", 8, rows=np.array([1]), horizon=2)
    pd.testing.assert_frame_equal(one.reset_index(drop=True), full.iloc[[1]].reset_index(drop=True))
    gas = features_at(panel, "gas", 8, rows=np.array([0]), horizon=2).iloc[0]
    assert gas["log_rate_lag0"] == pytest.approx(math.log1p(2.0))  # 2 x the oil rate
    assert gas["log_gor"] == pytest.approx(ln_ratio(14 / 3, 7 / 3))  # the same for both fluids


def test_the_base_rate_is_the_mean_of_the_last_three_months() -> None:
    panel = hand_panel()
    assert base_rate(panel, "oil", 8).tolist() == pytest.approx([7 / 3, 5.0])
    assert base_rate(panel, "oil", 2, rows=np.array([0])).tolist() == pytest.approx([15.0])  # the missing month is skipped
    assert math.isnan(base_rate(panel, "oil", 0, rows=np.array([0]))[0])


def test_features_at_a_column_do_not_depend_on_later_columns() -> None:
    panel = synthetic_panel(n_wells=10, n_months=48, seed=4)
    for col in (10, 30):
        changed = perturb_after(panel, col, keep_gaps=False)
        for fluid in ("oil", "gas"):
            pd.testing.assert_frame_equal(features_at(panel, fluid, col, horizon=3), features_at(changed, fluid, col, horizon=3))
            assert np.array_equal(base_rate(panel, fluid, col), base_rate(changed, fluid, col), equal_nan=True)
    moved = perturb_after(panel, 29, keep_gaps=False)  # changes column 30: the features of column 30 must see it
    assert not features_at(panel, "oil", 30, horizon=3).equals(features_at(moved, "oil", 30, horizon=3))


# --- training examples ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def panel() -> SeriesPanel:
    return synthetic_panel(n_wells=14, n_months=48, seed=6, young_wells=3)


def cfg_with(**changes):
    return dataclasses.replace(ML, **changes)


def brute_force(panel: SeriesPanel, fluid: str, horizon: int, origin_col: int, window: int) -> list[tuple[int, int, float]]:
    """(well row, t, y) of every example, written the long way from the definition."""
    rate = panel.rate[fluid]
    out = []
    for u in range(origin_col - window + 1, origin_col + 1):
        t = u - horizon
        if t < 0:
            continue
        for w in range(rate.shape[0]):
            recent = rate[w, max(0, t - 2) : t + 1]
            if not np.any(recent > 0) or np.isnan(rate[w, u]):
                continue
            m3 = np.nanmean(recent)
            out.append((w, t, math.log((rate[w, u] + EPS) / (m3 + EPS))))
    return out


def test_the_target_months_of_the_examples_end_at_the_origin() -> None:
    cfg = cfg_with(train_window_months=60)
    assert training_target_range(100, 3, cfg) == (100 - 59 - 3, 100 - 3)  # t of the first and the last example
    assert training_target_range(100, 12, cfg_with(train_window_months=10)) == (100 - 9 - 12, 100 - 12)
    lo, hi = training_target_range(40, 3, cfg_with(train_window_months=10))
    assert hi + 3 == 40  # the last target is the origin itself, never later


@pytest.mark.parametrize(("fluid", "horizon", "origin_col"), [("oil", 3, 40), ("gas", 1, 46), ("oil", 12, 44)])
def test_the_examples_are_every_active_series_month_with_a_known_target(panel: SeriesPanel, fluid: str, horizon: int, origin_col: int) -> None:
    cfg = cfg_with(train_window_months=10, max_train_rows=10**6)
    X, y = training_examples(panel, fluid, horizon, origin_col, cfg, EPS)
    expected = brute_force(panel, fluid, horizon, origin_col, 10)
    assert len(X) == len(y) == len(expected) > 0
    assert sorted(np.round(y, 9)) == pytest.approx(sorted(round(v[2], 9) for v in expected))
    assert list(X.columns) == [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
    assert np.isfinite(y).all()


def test_young_series_are_part_of_the_training_set(panel: SeriesPanel) -> None:
    cfg = cfg_with(train_window_months=6, max_train_rows=10**6)
    X, _ = training_examples(panel, "oil", 1, 46, cfg, EPS)
    assert (X["months_since_first"] < 3).any()  # the wells that started four months before the end


def test_training_never_looks_beyond_the_origin(panel: SeriesPanel) -> None:
    cfg = cfg_with(train_window_months=24, max_train_rows=10**6)
    for origin_col in (25, 38):
        X, y = training_examples(panel, "oil", 3, origin_col, cfg, EPS)
        changed = perturb_after(panel, origin_col, keep_gaps=False)
        X2, y2 = training_examples(changed, "oil", 3, origin_col, cfg, EPS)
        pd.testing.assert_frame_equal(X, X2)
        assert np.array_equal(y, y2)
    # ... but the origin month itself is a legitimate target: changing it must change the examples.
    moved = perturb_after(panel, 37, keep_gaps=False)
    X3, y3 = training_examples(moved, "oil", 3, 38, cfg, EPS)
    assert not np.array_equal(training_examples(panel, "oil", 3, 38, cfg, EPS)[1], y3)


def test_a_large_set_is_sampled_with_a_fixed_seed(panel: SeriesPanel) -> None:
    full, _ = training_examples(panel, "oil", 3, 40, cfg_with(max_train_rows=10**6), EPS)
    assert len(full) > 150
    cfg = cfg_with(max_train_rows=150)
    X1, y1 = training_examples(panel, "oil", 3, 40, cfg, EPS)
    X2, y2 = training_examples(panel, "oil", 3, 40, cfg, EPS)
    assert len(X1) == len(y1) == 150
    pd.testing.assert_frame_equal(X1, X2)
    assert np.array_equal(y1, y2)
    X3, _ = training_examples(panel, "oil", 3, 40, cfg_with(max_train_rows=150, seed=7), EPS)
    assert not X1.equals(X3)


def test_no_examples_when_nothing_is_known_yet(panel: SeriesPanel) -> None:
    X, y = training_examples(panel, "oil", 3, 1, cfg_with(train_window_months=60), EPS)
    assert len(X) == len(y) == 0 and list(X.columns) == [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
