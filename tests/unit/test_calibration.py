"""Empirical P10/P90 bands from errors already realized before the origin (RF12, D09, AC11)."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from oilgas.calibration import apply_bands, band_quantiles, calibration_pool, log_error
from oilgas.config import load_config

CFG = load_config().backtest


def error_rows(origins, horizon=3, method="m", fluid="oil", bucket="12-23", values=None) -> pd.DataFrame:
    n = len(origins)
    return pd.DataFrame(
        {
            "method": method, "fluid": fluid, "horizon": horizon, "origin": list(origins),
            "age_bucket": bucket, "error": np.arange(n, dtype=float) if values is None else values,
        }
    )


def test_log_error_is_the_log_ratio_of_the_rates_shifted_by_epsilon() -> None:
    got = log_error(np.array([10.0, 0.0]), np.array([8.0, 5.0]), 0.1)
    assert got.tolist() == pytest.approx([math.log(10.1 / 8.1), math.log(0.1 / 5.1)])
    assert log_error(np.array([5.0]), np.array([5.0]), 0.1)[0] == 0.0  # a perfect forecast has no error
    assert np.isfinite(log_error(np.array([0.0]), np.array([0.0]), 0.1)).all()  # months in zero are fine


def test_the_pool_holds_the_twelve_latest_origins_whose_target_is_known() -> None:
    errors = pd.concat([error_rows(range(0, 31), horizon=3), error_rows(range(0, 31), horizon=12)], ignore_index=True)
    pool = calibration_pool(errors, origin=20, horizon=3, window=12)
    assert sorted(pool["origin"].unique()) == list(range(6, 18))  # [o - h - 11, o - h]
    assert (pool["horizon"] == 3).all()
    assert (pool["origin"] + pool["horizon"]).max() <= 20  # the target month is not after the origin
    long = calibration_pool(errors, origin=20, horizon=12, window=12)
    assert sorted(long["origin"].unique()) == [0, 1, 2, 3, 4, 5, 6, 7, 8]  # [-3, 8] clipped by the data
    assert sorted(calibration_pool(errors, origin=20, horizon=3, window=4)["origin"].unique()) == [14, 15, 16, 17]
    assert calibration_pool(errors, origin=2, horizon=3, window=12).empty  # nothing is known yet


def test_errors_with_a_target_after_the_origin_never_enter_the_bands() -> None:
    clean = error_rows(range(0, 18), horizon=3, values=np.linspace(-1, 1, 18))
    future = error_rows([18, 19, 20, 25], horizon=3, values=[500.0, 500.0, 500.0, 500.0])  # their targets are 21+
    base = band_quantiles(clean, 20, CFG)
    both = band_quantiles(pd.concat([clean, future], ignore_index=True), 20, CFG)
    pd.testing.assert_frame_equal(base, both)
    assert base["q90"].max() < 2


def test_quantiles_per_cell_with_enough_samples() -> None:
    values = np.arange(1.0, 301.0)  # 300 errors in one cell, 25 origins x 12 rows
    errors = error_rows(np.repeat(np.arange(25), 12), horizon=1, values=values)
    cfg = dataclasses.replace(CFG, min_calibration_samples=100)
    out = band_quantiles(errors, 25, cfg)
    cell = out[out["age_bucket"] == "12-23"].iloc[0]
    pool = errors[errors["origin"].between(25 - 1 - 11, 24)]
    assert cell["n"] == len(pool) and cell["level"] == "cell"
    assert cell["q10"] == pytest.approx(np.quantile(pool["error"], 0.1))
    assert cell["q90"] == pytest.approx(np.quantile(pool["error"], 0.9))
    star = out[out["age_bucket"] == "*"].iloc[0]
    assert star["level"] == "method" and star["q10"] == pytest.approx(cell["q10"])


def test_a_cell_with_few_samples_uses_the_quantiles_of_the_whole_method() -> None:
    big = error_rows(np.repeat(np.arange(12), 30), horizon=1, bucket="24-59", values=np.tile(np.arange(30.0), 12))
    small = error_rows([3, 4, 5], horizon=1, bucket="60+", values=[100.0, 200.0, 300.0])
    errors = pd.concat([big, small], ignore_index=True)
    cfg = dataclasses.replace(CFG, min_calibration_samples=200)
    out = band_quantiles(errors, 12, cfg).set_index("age_bucket")
    pooled = errors[errors["origin"].between(0, 11)]["error"]
    assert out.loc["24-59", "level"] == "cell" and out.loc["24-59", "n"] == 360
    assert out.loc["60+", "level"] == "method" and out.loc["60+", "n"] == 3  # n is the cell's own count
    assert out.loc["60+", "q10"] == pytest.approx(np.quantile(pooled, 0.1))
    assert out.loc["60+", "q90"] == pytest.approx(np.quantile(pooled, 0.9))
    assert out.loc["*", "q90"] == pytest.approx(np.quantile(pooled, 0.9))


def test_bands_are_kept_apart_by_method_fluid_and_horizon() -> None:
    parts = []
    for method, fluid, horizon, level in (("a", "oil", 1, 1.0), ("a", "gas", 1, 2.0), ("b", "oil", 1, 3.0), ("a", "oil", 6, 4.0)):
        parts.append(error_rows(np.repeat(np.arange(30), 10), horizon=horizon, method=method, fluid=fluid, values=np.full(300, level)))
    out = band_quantiles(pd.concat(parts, ignore_index=True), 30, dataclasses.replace(CFG, min_calibration_samples=100))
    star = out[out["age_bucket"] == "*"].set_index(["method", "fluid", "horizon"])
    assert star.loc[("a", "oil", 1), "q10"] == 1.0 and star.loc[("a", "gas", 1), "q10"] == 2.0
    assert star.loc[("b", "oil", 1), "q90"] == 3.0 and star.loc[("a", "oil", 6), "q90"] == 4.0
    assert len(star) == 4


def test_no_errors_yet_gives_no_bands() -> None:
    out = band_quantiles(error_rows([5, 6, 7], horizon=12), 8, CFG)  # their targets (17+) are after the origin
    assert out.empty and {"method", "fluid", "horizon", "age_bucket", "q10", "q90", "n", "level"} <= set(out.columns)


def test_applying_bands_scales_the_forecast_rate_by_the_error_quantiles() -> None:
    p10, p90 = apply_bands(np.array([10.0]), np.array([math.log(0.5)]), np.array([math.log(2.0)]), 0.1)
    assert p10[0] == pytest.approx(10.1 * 0.5 - 0.1) and p90[0] == pytest.approx(10.1 * 2.0 - 0.1)


def test_the_bands_never_go_below_zero_and_always_surround_the_median() -> None:
    p10, p90 = apply_bands(np.array([0.0, 10.0, 10.0]), np.array([-3.0, 0.4, -0.2]), np.array([0.5, 0.3, -0.1]), 0.1)
    assert p10[0] == 0.0  # 0.1 * exp(-3) - 0.1 would be negative
    assert p10[1] == 10.0 and p90[1] > 10.0  # all errors positive: P10 is the median, not above it
    assert p90[2] == 10.0 and p10[2] < 10.0  # all errors negative: P90 is the median, not below it
    assert (p10 <= np.array([0.0, 10.0, 10.0])).all()


def test_the_order_is_exact_even_where_rounding_would_break_it() -> None:
    rng = np.random.default_rng(0)
    median = rng.uniform(0, 5000, size=5000)
    p10, p90 = apply_bands(median, np.zeros(5000), np.zeros(5000), 0.1)  # no spread at all: the band is the median
    assert (p10 <= median).all() and (median <= p90).all()
    assert np.allclose(p10, median, rtol=1e-12, atol=1e-12) and np.allclose(p90, median, rtol=1e-12, atol=1e-12)


def test_nan_quantiles_give_nan_bands() -> None:
    p10, p90 = apply_bands(np.array([10.0]), np.array([np.nan]), np.array([np.nan]), 0.1)
    assert np.isnan(p10[0]) and np.isnan(p90[0])
