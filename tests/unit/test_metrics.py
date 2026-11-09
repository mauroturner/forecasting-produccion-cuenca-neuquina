"""Metrics with values worked out by hand: point errors, bands, pinball, additive components, share_beats."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from oilgas.metrics import (
    additive_components,
    bias,
    coverage,
    mae,
    pinball,
    rmse,
    scaled_pinball,
    share_beats,
    wape,
)

Y = np.array([10.0, 20.0, 0.0, 30.0])
YHAT = np.array([12.0, 18.0, 5.0, 30.0])  # errors +2, -2, +5, 0


def test_point_metrics() -> None:
    assert mae(Y, YHAT) == pytest.approx(9 / 4)
    assert rmse(Y, YHAT) == pytest.approx(math.sqrt(33 / 4))
    assert wape(Y, YHAT) == pytest.approx(9 / 60)  # sum |error| / sum actual: months in zero do not break it
    assert bias(Y, YHAT) == pytest.approx(5 / 60)  # sum (forecast - actual) / sum actual


def test_metrics_of_nothing_or_of_a_zero_total_are_nan_not_errors() -> None:
    empty = np.array([])
    for metric in (mae, rmse, wape, bias):
        assert math.isnan(metric(empty, empty))
    zeros = np.zeros(3)
    assert math.isnan(wape(zeros, zeros + 1)) and math.isnan(bias(zeros, zeros + 1))
    assert mae(zeros, zeros + 1) == 1.0


def test_coverage_counts_the_actuals_inside_the_band_edges_included() -> None:
    lo, hi = np.array([8.0, 25.0, 0.0, 31.0]), np.array([15.0, 30.0, 2.0, 35.0])
    assert coverage(Y, lo, hi) == 0.5  # 10 in, 20 out, 0 in (the edge), 30 out
    assert math.isnan(coverage(np.array([]), np.array([]), np.array([])))


def test_pinball_loss_of_one_quantile() -> None:
    y = np.array([10.0, 10.0])
    q = np.array([8.0, 12.0])
    assert pinball(y, q, 0.9).tolist() == pytest.approx([0.9 * 2, 0.1 * 2])  # under-forecast costs alpha, over 1 - alpha
    assert pinball(y, q, 0.5).tolist() == pytest.approx([1.0, 1.0])
    assert pinball(y, y, 0.1).tolist() == [0.0, 0.0]


def test_scaled_pinball_sums_the_three_quantiles_over_the_total_actual() -> None:
    y, p10, p50, p90 = np.array([10.0, 20.0]), np.array([8.0, 25.0]), np.array([12.0, 18.0]), np.array([15.0, 30.0])
    # y=10: 0.2 + 1.0 + 0.5 = 1.7; y=20: 4.5 + 1.0 + 1.0 = 6.5
    assert scaled_pinball(y, p10, p50, p90) == pytest.approx(8.2 / 30)
    assert math.isnan(scaled_pinball(np.zeros(2), p10, p50, p90))


def components_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "method": ["a", "a", "b"],
            "fluid": ["oil", "oil", "oil"],
            "actual": [10.0, 20.0, 5.0],
            "p10": [8.0, 25.0, 4.0],
            "p50": [12.0, 18.0, 5.0],
            "p90": [15.0, 30.0, 9.0],
        }
    )


def test_additive_components_are_the_sums_every_metric_is_built_from() -> None:
    out = additive_components(components_frame(), ["method"]).set_index("method")
    a = out.loc["a"]
    assert a["n"] == 2 and a["sum_actual"] == 30 and a["sum_p10"] == 33 and a["sum_p50"] == 30 and a["sum_p90"] == 45
    assert a["sum_abs_error"] == 4 and a["sum_sq_error"] == 8
    assert a["sum_error"] == 0  # (12 - 10) + (18 - 20): forecast minus actual
    assert a["n_covered"] == 1  # 10 is inside [8, 15], 20 is outside [25, 30]
    assert a["sum_pinball"] == pytest.approx(8.2)
    b = out.loc["b"]
    assert b["n"] == 1 and b["n_covered"] == 1 and b["sum_abs_error"] == 0
    assert b["sum_pinball"] == pytest.approx(0.1 + 0.0 + 0.4)  # y=5 against 4, 5 and 9


def test_components_rebuild_the_metrics_of_the_rows() -> None:
    frame = pd.DataFrame({"g": "x", "actual": Y, "p10": Y - 3, "p50": YHAT, "p90": Y + 4})
    c = additive_components(frame, ["g"]).iloc[0]
    assert c["sum_abs_error"] / c["n"] == pytest.approx(mae(Y, YHAT))
    assert math.sqrt(c["sum_sq_error"] / c["n"]) == pytest.approx(rmse(Y, YHAT))
    assert c["sum_abs_error"] / c["sum_actual"] == pytest.approx(wape(Y, YHAT))
    assert c["sum_error"] / c["sum_actual"] == pytest.approx(bias(Y, YHAT))
    assert c["n_covered"] / c["n"] == coverage(Y, Y - 3, Y + 4)
    assert c["sum_pinball"] / c["sum_actual"] == pytest.approx(scaled_pinball(Y, Y - 3, YHAT, Y + 4))


def test_components_add_up_across_groups() -> None:
    frame = components_frame()
    whole = additive_components(frame, ["fluid"]).iloc[0]
    parts = additive_components(frame, ["method"])
    for column in ("n", "sum_actual", "sum_p50", "sum_abs_error", "sum_sq_error", "n_covered", "sum_pinball"):
        assert whole[column] == pytest.approx(parts[column].sum())


def test_share_beats_counts_the_series_whose_mean_absolute_error_is_strictly_lower() -> None:
    rows = []
    # (well, origin, actual, method p50, baseline p50)
    for well, origin, actual, m, b in [
        (1, 1, 10.0, 11.0, 14.0), (1, 2, 10.0, 12.0, 13.0),  # method MAE 1.5, baseline 3.5: beats
        (2, 1, 10.0, 15.0, 11.0), (2, 2, 10.0, 16.0, 12.0),  # method 5.5, baseline 1.5: does not
        (3, 1, 10.0, 12.0, 8.0), (3, 2, 10.0, 8.0, 12.0),    # 2.0 and 2.0: a tie is not beating
    ]:
        rows.append(("oil", well, origin, 1, "m", actual, m))
        rows.append(("oil", well, origin, 1, "b", actual, b))
    rows.append(("oil", 4, 1, 1, "m", 10.0, 10.0))  # no baseline row: the series is not compared
    rows.append(("gas", 1, 1, 1, "m", 10.0, 10.0))
    rows.append(("gas", 1, 1, 1, "b", 10.0, 20.0))
    frame = pd.DataFrame(rows, columns=["fluid", "well_id", "origin", "horizon", "method", "actual", "p50"])
    out = share_beats(frame, "m", "b").set_index(["fluid", "horizon"])
    assert out.loc[("oil", 1), "n_series"] == 3 and out.loc[("oil", 1), "n_beats"] == 1
    assert out.loc[("oil", 1), "share"] == pytest.approx(1 / 3)
    assert out.loc[("gas", 1), "n_series"] == 1 and out.loc[("gas", 1), "share"] == 1.0


def test_share_beats_groups_by_the_requested_columns_and_ignores_other_methods() -> None:
    rows = []
    for method, p50 in (("m", 11.0), ("b", 15.0), ("other", 0.0)):
        for well, segment in ((1, "eligible"), (2, "young")):
            rows.append(("oil", well, 1, 3, method, 10.0, p50 if well == 1 else 30.0 - p50, segment))
    frame = pd.DataFrame(rows, columns=["fluid", "well_id", "origin", "horizon", "method", "actual", "p50", "segment"])
    out = share_beats(frame, "m", "b", by=["fluid", "horizon", "segment"]).set_index("segment")
    assert out.loc["eligible", "share"] == 1.0  # |11 - 10| < |15 - 10|
    assert out.loc["young", "share"] == 0.0  # 30 - 11 = 19 against 30 - 15 = 15
