"""Arps decline curves: shapes, exact and noisy fits, bounds, warm start and the fallback chain (AC07-AC09)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from oilgas import arps
from oilgas.arps import (
    D_LIM_DEFAULT,
    ArpsParams,
    effective_annual_initial,
    exponential_log_rate,
    fit_series,
    hyperbolic_log_rate,
    modified_hyperbolic_log_rate,
    nominal_from_effective_annual,
    predict_rate,
    switch_time,
)
from oilgas.config import load_config
from tests.fixtures.make_fixture import modified_hyperbolic_rate

CFG = load_config().arps
D_LIM = D_LIM_DEFAULT
GRID = np.arange(0.0, 240.0, 0.5)


# --- the curves (AC09) ------------------------------------------------------------------------------


def test_the_terminal_decline_is_ten_percent_effective_per_year() -> None:
    assert nominal_from_effective_annual(0.10) == pytest.approx(-math.log(0.9) / 12)
    assert nominal_from_effective_annual(0.10) == pytest.approx(0.0087800, abs=1e-7)
    assert D_LIM_DEFAULT == nominal_from_effective_annual(CFG.terminal_decline_effective_annual)
    for effective in (0.05, 0.3, 0.6):
        monthly = nominal_from_effective_annual(effective)
        assert 1 - math.exp(-12 * monthly) == pytest.approx(effective)


def test_exponential_and_hyperbolic_log_rates_by_hand() -> None:
    t = np.array([0.0, 1.0, 10.0])
    assert exponential_log_rate(t, math.log(100), 0.1).tolist() == pytest.approx([math.log(100) - 0.1 * x for x in t])
    expected = [math.log(100) - math.log1p(1.5 * 0.2 * x) / 1.5 for x in t]
    assert hyperbolic_log_rate(t, math.log(100), 0.2, 1.5).tolist() == pytest.approx(expected)
    assert hyperbolic_log_rate(np.array([0.0]), math.log(80), 0.3, 1.0)[0] == pytest.approx(math.log(80))
    # With b -> 0 the hyperbolic is the exponential.
    assert hyperbolic_log_rate(t, 4.0, 0.2, 1e-9).tolist() == pytest.approx(exponential_log_rate(t, 4.0, 0.2).tolist(), abs=1e-6)


@pytest.mark.parametrize(("di", "b"), [(0.15, 1.2), (0.3, 2.0), (0.05, 0.4), (0.9, 0.05), (0.02, 1.0)])
def test_modified_hyperbolic_matches_the_generator_of_the_fixtures(di: float, b: float) -> None:
    got = modified_hyperbolic_log_rate(GRID, math.log(500), di, b, D_LIM)
    want = np.log(modified_hyperbolic_rate(GRID, 500.0, di, b, D_LIM))
    assert np.allclose(got, want, rtol=0, atol=1e-11)


@pytest.mark.parametrize(("di", "b"), [(0.15, 1.2), (0.3, 2.0), (0.05, 0.4)])
def test_modified_hyperbolic_is_continuous_at_the_switch_and_declines_at_the_limit_after_it(di: float, b: float) -> None:
    ts = switch_time(di, b, D_LIM)
    assert ts == pytest.approx((di / D_LIM - 1) / (b * di)) and ts > 0
    eps = 1e-8
    left = modified_hyperbolic_log_rate(np.array([ts - eps]), 0.0, di, b, D_LIM)[0]
    right = modified_hyperbolic_log_rate(np.array([ts + eps]), 0.0, di, b, D_LIM)[0]
    assert abs(math.expm1(right - left)) < 1e-9  # relative difference of the rate across the switch
    # Nominal decline = -d ln q / dt: the limit after the switch, higher before it.
    after = np.array([ts + 5.0, ts + 6.0, ts + 40.0, ts + 41.0])
    ln_q = modified_hyperbolic_log_rate(after, 0.0, di, b, D_LIM)
    assert -(ln_q[1] - ln_q[0]) == pytest.approx(D_LIM, rel=1e-9)
    assert -(ln_q[3] - ln_q[2]) == pytest.approx(D_LIM, rel=1e-9)
    before = modified_hyperbolic_log_rate(np.array([ts - 6.0, ts - 5.0]), 0.0, di, b, D_LIM)
    assert -(before[1] - before[0]) > D_LIM
    # The hyperbolic decline at the switch is the limit by construction.
    assert di / (1 + b * di * ts) == pytest.approx(D_LIM)


def test_with_an_initial_decline_below_the_limit_the_curve_is_an_exponential_with_that_decline() -> None:
    di = D_LIM / 2
    assert switch_time(di, 1.0, D_LIM) == 0.0
    got = modified_hyperbolic_log_rate(GRID, 3.0, di, 1.0, D_LIM)
    assert np.allclose(got, exponential_log_rate(GRID, 3.0, di))


def test_predicting_a_rate_and_the_initial_effective_decline() -> None:
    mh = ArpsParams("arps_mh_b2", math.log(500), 0.15, 1.2, D_LIM, switch_time(0.15, 1.2, D_LIM))
    t = np.array([0.0, 12.0, 60.0])
    assert predict_rate(mh, t).tolist() == pytest.approx(modified_hyperbolic_rate(t, 500.0, 0.15, 1.2, D_LIM).tolist())
    assert effective_annual_initial(mh) == pytest.approx(1 - (1 + 12 * 1.2 * 0.15) ** (-1 / 1.2))
    exp = ArpsParams("arps_exp", math.log(300), 0.08, 0.0, D_LIM, 0.0)
    assert predict_rate(exp, t).tolist() == pytest.approx((300 * np.exp(-0.08 * t)).tolist())
    assert effective_annual_initial(exp) == pytest.approx(1 - math.exp(-12 * 0.08))
    slow = ArpsParams("arps_mh_b2", math.log(10), D_LIM / 2, 1.0, D_LIM, 0.0)  # below the limit: exponential
    assert effective_annual_initial(slow) == pytest.approx(1 - math.exp(-12 * D_LIM / 2))


# --- exact fits (AC07) ------------------------------------------------------------------------------


def test_a_noiseless_modified_hyperbolic_is_recovered() -> None:
    t = np.arange(48.0)
    rate = modified_hyperbolic_rate(t, 500.0, 0.15, 1.2, D_LIM)
    fit = fit_series(t, rate, "arps_mh_b2", CFG)
    assert fit.status == "ok" and fit.n_points == 48 and fit.params is not None
    p = fit.params
    assert p.method == "arps_mh_b2" and p.d_lim == pytest.approx(D_LIM)
    assert math.exp(p.log_qi) == pytest.approx(500.0, rel=0.01)
    assert p.di == pytest.approx(0.15, rel=0.03)
    assert p.b == pytest.approx(1.2, abs=0.05)
    assert p.t_switch == pytest.approx(switch_time(p.di, p.b, D_LIM))
    assert fit.rmse_log < 1e-3
    for months in (12.0, 47.0 + 12.0):  # inside the data and 12 months past it
        truth = modified_hyperbolic_rate(np.array([months]), 500.0, 0.15, 1.2, D_LIM)[0]
        assert predict_rate(p, np.array([months]))[0] == pytest.approx(truth, rel=0.01)


def test_a_noiseless_exponential_is_recovered() -> None:
    t = np.arange(36.0)
    rate = 400.0 * np.exp(-0.08 * t)
    fit = fit_series(t, rate, "arps_exp", CFG)
    assert fit.status == "ok" and fit.params is not None and fit.params.method == "arps_exp"
    assert fit.params.di == pytest.approx(0.08, rel=0.01)
    assert math.exp(fit.params.log_qi) == pytest.approx(400.0, rel=0.01)
    assert fit.params.b == 0.0 and fit.params.t_switch == 0.0


def test_the_sensitivity_variant_cannot_exceed_b_of_one() -> None:
    t = np.arange(48.0)
    rate = modified_hyperbolic_rate(t, 500.0, 0.15, 1.5, D_LIM)
    base = fit_series(t, rate, "arps_mh_b2", CFG)
    limited = fit_series(t, rate, "arps_mh_b1", CFG)
    assert base.params is not None and limited.params is not None
    assert base.params.b == pytest.approx(1.5, abs=0.1) and limited.params.b <= CFG.b_bounds_sensitivity[1] + 1e-12
    assert limited.params.method == "arps_mh_b1" and limited.rmse_log > base.rmse_log


# --- noisy fits (AC08) and bounds -------------------------------------------------------------------


def noisy_curves(n: int, seed: int, history: int):
    rng = np.random.default_rng(seed)
    t = np.arange(float(history))
    for _ in range(n):
        qi = float(np.clip(np.exp(rng.normal(math.log(300), 0.6)), 30, 2000))
        di, b = float(rng.uniform(0.05, 0.3)), float(rng.uniform(0.3, 1.5))
        noise = np.exp(rng.normal(0, 0.1, size=history))
        yield qi, di, b, t, modified_hyperbolic_rate(t, qi, di, b, D_LIM) * noise


def test_with_lognormal_noise_the_error_at_twelve_months_is_small() -> None:
    """200 curves, sigma = 0.1, seed 0: fitted on 36 months, the rate 12 months later against the noiseless truth."""
    errors = []
    for qi, di, b, t, rate in noisy_curves(200, seed=0, history=36):
        fit = fit_series(t, rate, "arps_mh_b2", CFG)
        assert fit.params is not None
        horizon = np.array([35.0 + 12.0])
        truth = modified_hyperbolic_rate(horizon, qi, di, b, D_LIM)[0]
        errors.append(abs(predict_rate(fit.params, horizon)[0] / truth - 1))
    assert np.median(errors) <= 0.05
    assert np.quantile(errors, 0.9) <= 0.15


@pytest.mark.parametrize("method", ["arps_exp", "arps_mh_b2", "arps_mh_b1"])
def test_fitted_parameters_always_stay_inside_their_bounds(method: str) -> None:
    rng = np.random.default_rng(7)
    shapes = [
        np.linspace(100, 10, 20),  # decline
        np.linspace(10, 100, 20),  # growth after the "peak" (the caller should not send it, but it must not escape)
        np.full(20, 50.0),  # flat
        np.exp(rng.normal(3, 1.5, size=20)),  # noise only
        50 * np.exp(-1.5 * np.arange(20.0)) + 1e-3,  # collapse
    ]
    di_bounds = CFG.di_bounds_exp_per_month if method == "arps_exp" else CFG.di_bounds_per_month
    b_bounds = CFG.b_bounds_sensitivity if method == "arps_mh_b1" else CFG.b_bounds_base
    for rate in shapes:
        fit = fit_series(np.arange(20.0), rate, method, CFG)
        assert fit.params is not None
        p, peak = fit.params, float(rate.max())
        assert di_bounds[0] - 1e-12 <= p.di <= di_bounds[1] + 1e-12
        assert abs(p.log_qi - math.log(peak)) <= math.log(CFG.qi_bound_factor) + 1e-9
        if method != "arps_exp":
            assert b_bounds[0] - 1e-12 <= p.b <= b_bounds[1] + 1e-12


def test_the_fit_is_deterministic() -> None:
    _, _, _, t, rate = next(noisy_curves(1, seed=3, history=30))
    first, second = fit_series(t, rate, "arps_mh_b2", CFG), fit_series(t, rate, "arps_mh_b2", CFG)
    assert first == second


def test_rmse_in_log_scale_is_about_the_noise_level() -> None:
    values = [fit_series(t, r, "arps_mh_b2", CFG).rmse_log for _, _, _, t, r in noisy_curves(40, seed=5, history=36)]
    assert 0.05 < float(np.median(values)) < 0.12  # sigma = 0.1, a little less after fitting three parameters


def test_inputs_must_be_matching_positive_numbers() -> None:
    with pytest.raises(ValueError, match="same length"):
        fit_series(np.arange(5.0), np.ones(4), "arps_mh_b2", CFG)
    with pytest.raises(ValueError, match="positive"):
        fit_series(np.arange(3.0), np.array([5.0, 0.0, 3.0]), "arps_mh_b2", CFG)
    with pytest.raises(ValueError, match="unknown method"):
        fit_series(np.arange(3.0), np.ones(3), "arps_nope", CFG)


# --- fallback chain and warm start ------------------------------------------------------------------


def test_with_too_few_points_the_hyperbolic_falls_back_to_the_exponential_and_then_to_the_naive() -> None:
    two = fit_series(np.array([0.0, 1.0]), np.array([100.0, 90.0]), "arps_mh_b2", CFG)
    assert two.status == "fallback_exp" and two.params is not None and two.params.method == "arps_exp"
    assert two.params.di == pytest.approx(-math.log(0.9), rel=1e-3) and two.n_points == 2
    one = fit_series(np.array([0.0]), np.array([100.0]), "arps_mh_b1", CFG)
    assert one.status == "fallback_naive" and one.params is None and one.n_points == 1 and math.isnan(one.rmse_log)
    assert fit_series(np.array([0.0]), np.array([100.0]), "arps_exp", CFG).status == "fallback_naive"


def test_optimizer_failures_follow_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    t = np.arange(24.0)
    rate = modified_hyperbolic_rate(t, 200.0, 0.1, 1.0, D_LIM)
    real = arps.curve_fit

    def fails_for_three_parameters(f, x, y, p0=None, **kwargs):
        if len(p0) == 3:
            raise RuntimeError("Optimal parameters not found")
        return real(f, x, y, p0=p0, **kwargs)

    monkeypatch.setattr(arps, "curve_fit", fails_for_three_parameters)
    fit = fit_series(t, rate, "arps_mh_b2", CFG)
    assert fit.status == "fallback_exp" and fit.params is not None and fit.params.method == "arps_exp"
    assert fit.n_points == 24 and math.isfinite(fit.rmse_log)

    def always_fails(f, x, y, p0=None, **kwargs):
        raise ValueError("`x0` is infeasible.")

    monkeypatch.setattr(arps, "curve_fit", always_fails)
    for method in ("arps_mh_b2", "arps_mh_b1", "arps_exp"):
        fit = fit_series(t, rate, method, CFG)
        assert fit.status == "fallback_naive" and fit.params is None and fit.n_points == 24


def test_a_solution_with_non_finite_parameters_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    t = np.arange(12.0)
    rate = 100.0 * np.exp(-0.1 * t)
    monkeypatch.setattr(arps, "curve_fit", lambda f, x, y, p0=None, **kw: (np.full(len(p0), np.nan), None))
    assert fit_series(t, rate, "arps_mh_b2", CFG).status == "fallback_naive"


def solves(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = arps.curve_fit

    def counting(f, x, y, p0=None, **kwargs):
        calls.append(len(p0))
        return real(f, x, y, p0=p0, **kwargs)

    monkeypatch.setattr(arps, "curve_fit", counting)
    return calls


def test_a_cold_fit_tries_one_start_per_b_and_a_warm_fit_tries_the_previous_solution_and_one_more(monkeypatch: pytest.MonkeyPatch) -> None:
    t = np.arange(30.0)
    rate = modified_hyperbolic_rate(t, 300.0, 0.12, 1.1, D_LIM)
    calls = solves(monkeypatch)
    cold = fit_series(t, rate, "arps_mh_b2", CFG)
    assert len(calls) == len(CFG.b_starts_base) == 3
    calls.clear()
    fit_series(t, rate, "arps_mh_b1", CFG)
    assert len(calls) == len(CFG.b_starts_sensitivity) == 2
    calls.clear()
    warm = fit_series(t[:-1], rate[:-1], "arps_mh_b2", CFG, warm_start=cold.params)
    assert len(calls) == 2 and warm.status == "ok" and warm.params is not None
    assert warm.params.b == pytest.approx(1.1, abs=0.05)
    calls.clear()
    other_method = ArpsParams("arps_exp", 5.0, 0.05, 0.0, D_LIM, 0.0)
    fit_series(t, rate, "arps_mh_b2", CFG, warm_start=other_method)  # a solution of another variant is not a warm start
    assert len(calls) == 3
    calls.clear()
    fit_series(t, rate, "arps_exp", CFG)
    assert len(calls) == 1


def test_a_warm_start_outside_the_bounds_is_clipped_not_rejected() -> None:
    t = np.arange(30.0)
    rate = modified_hyperbolic_rate(t, 300.0, 0.12, 0.8, D_LIM)
    wild = ArpsParams("arps_mh_b1", math.log(1e9), 50.0, 9.0, D_LIM, 0.0)
    fit = fit_series(t, rate, "arps_mh_b1", CFG, warm_start=wild)
    assert fit.status == "ok" and fit.params is not None and fit.params.b == pytest.approx(0.8, abs=0.05)
