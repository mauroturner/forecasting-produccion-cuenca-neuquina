"""Arps decline curves fitted in log scale (RF09, plan section 9.2, decision D06).

Rates ``q`` are in m3/d or thousand m3/d, time ``t`` in calendar months since the peak, declines are
nominal per month. Three variants, fixed in advance (the variant is never chosen by looking at the
test error):

- ``arps_exp``: ``ln q = ln qi - Di t``;
- ``arps_mh_b2`` (base case): modified hyperbolic, hyperbolic until its nominal decline falls to
  ``D_lim`` (10 % effective per year) and exponential from there, with ``b`` in [0.001, 2];
- ``arps_mh_b1`` (sensitivity): the same with ``b`` in [0.001, 1].

``fit_series`` falls back along ``mh -> exp -> naive`` when the optimizer fails, and says so in the
``status`` of its result.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit

from oilgas.config import ArpsConfig, load_config

METHODS = ("arps_exp", "arps_mh_b2", "arps_mh_b1")
EXPONENTIAL = "arps_exp"
FIRST_POINTS = 12  # points used for the slope that seeds the initial decline
WARM_B_START = 1.0


def nominal_from_effective_annual(d_eff_annual: float) -> float:
    """Nominal monthly decline equivalent to an effective annual one: ``-ln(1 - d) / 12``."""
    return -math.log(1.0 - d_eff_annual) / 12.0


D_LIM_DEFAULT = nominal_from_effective_annual(load_config().arps.terminal_decline_effective_annual)


@dataclass(frozen=True)
class ArpsParams:
    method: str
    log_qi: float
    di: float
    b: float  # 0 for the exponential
    d_lim: float
    t_switch: float  # months from the peak to the switch to the terminal exponential; 0 if there is none


@dataclass(frozen=True)
class FitResult:
    params: ArpsParams | None  # None when everything failed ("fallback_naive")
    status: Literal["ok", "fallback_exp", "fallback_naive"]
    n_points: int
    rmse_log: float


def switch_time(di: float, b: float, d_lim: float) -> float:
    """Months at which the hyperbolic nominal decline ``Di / (1 + b Di t)`` reaches `d_lim` (0 if it starts below it)."""
    if di <= d_lim:
        return 0.0
    return (di / d_lim - 1.0) / (b * di)


def exponential_log_rate(t: np.ndarray, log_qi: float, di: float) -> np.ndarray:
    return log_qi - di * np.asarray(t, dtype=np.float64)


def hyperbolic_log_rate(t: np.ndarray, log_qi: float, di: float, b: float) -> np.ndarray:
    return log_qi - np.log1p(b * di * np.asarray(t, dtype=np.float64)) / b


def modified_hyperbolic_log_rate(t: np.ndarray, log_qi: float, di: float, b: float, d_lim: float) -> np.ndarray:
    """Hyperbolic until `switch_time`, then exponential with `d_lim`; purely exponential with `di` if ``di <= d_lim``."""
    t = np.asarray(t, dtype=np.float64)
    if di <= d_lim:
        return exponential_log_rate(t, log_qi, di)
    t_switch = switch_time(di, b, d_lim)
    hyperbolic = hyperbolic_log_rate(np.minimum(t, t_switch), log_qi, di, b)
    log_q_switch = hyperbolic_log_rate(np.array(t_switch), log_qi, di, b)
    return np.where(t <= t_switch, hyperbolic, log_q_switch - d_lim * (t - t_switch))


def predict_rate(params: ArpsParams, t: np.ndarray) -> np.ndarray:
    """Rate at `t` months from the peak."""
    if params.method == EXPONENTIAL:
        return np.exp(exponential_log_rate(t, params.log_qi, params.di))
    return np.exp(modified_hyperbolic_log_rate(t, params.log_qi, params.di, params.b, params.d_lim))


def effective_annual_initial(params: ArpsParams) -> float:
    """Initial effective annual decline: ``1 - (1 + 12 b Di)^(-1/b)`` (``1 - exp(-12 Di)`` for the exponential)."""
    if params.method == EXPONENTIAL or params.di <= params.d_lim:
        return 1.0 - math.exp(-12.0 * params.di)
    return 1.0 - (1.0 + 12.0 * params.b * params.di) ** (-1.0 / params.b)


# --- fitting ----------------------------------------------------------------------------------------


def _bounds(method: str, log_peak: float, cfg: ArpsConfig) -> tuple[np.ndarray, np.ndarray]:
    spread = math.log(cfg.qi_bound_factor)
    if method == EXPONENTIAL:
        return (
            np.array([log_peak - spread, cfg.di_bounds_exp_per_month[0]]),
            np.array([log_peak + spread, cfg.di_bounds_exp_per_month[1]]),
        )
    b_low, b_high = cfg.b_bounds_sensitivity if method == "arps_mh_b1" else cfg.b_bounds_base
    return (
        np.array([log_peak - spread, cfg.di_bounds_per_month[0], b_low]),
        np.array([log_peak + spread, cfg.di_bounds_per_month[1], b_high]),
    )


def _starts(method: str, t: np.ndarray, log_rate: np.ndarray, lower: np.ndarray, upper: np.ndarray,
            cfg: ArpsConfig, warm_start: ArpsParams | None) -> list[np.ndarray]:
    log_peak = float(log_rate.max())
    k = min(FIRST_POINTS, len(t))
    slope = -0.05
    if k >= 2 and t[k - 1] > t[0]:
        slope = float(np.polyfit(t[:k], log_rate[:k], 1)[0])
    if method == EXPONENTIAL:
        di0 = float(np.clip(-slope, 0.001, 0.9))
        seeds = [np.array([log_peak, di0])]
    else:
        di0 = float(np.clip(-slope * 1.5, 0.01, 2.0))
        b_starts = cfg.b_starts_sensitivity if method == "arps_mh_b1" else cfg.b_starts_base
        warm = warm_start is not None and warm_start.method == method
        seeds = [np.array([log_peak, di0, b0]) for b0 in ((WARM_B_START,) if warm else b_starts)]
    if warm_start is not None and warm_start.method == method:
        previous = [warm_start.log_qi, warm_start.di] if method == EXPONENTIAL else [warm_start.log_qi, warm_start.di, warm_start.b]
        seeds.insert(0, np.array(previous, dtype=np.float64))
    return [np.clip(seed, lower, upper) for seed in seeds]


def _solve(method: str, t: np.ndarray, log_rate: np.ndarray, cfg: ArpsConfig, d_lim: float,
           warm_start: ArpsParams | None) -> tuple[ArpsParams, float] | None:
    """Best of the starts by sum of squares in log scale, or None if every start fails."""
    lower, upper = _bounds(method, float(log_rate.max()), cfg)
    if len(t) < len(lower):
        return None
    if method == EXPONENTIAL:
        def model(x, log_qi, di):
            return exponential_log_rate(x, log_qi, di)
    else:
        def model(x, log_qi, di, b):
            return modified_hyperbolic_log_rate(x, log_qi, di, b, d_lim)

    best: tuple[float, np.ndarray] | None = None
    for p0 in _starts(method, t, log_rate, lower, upper, cfg, warm_start):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", OptimizeWarning)
                popt, _ = curve_fit(
                    model, t, log_rate, p0=p0, bounds=(lower, upper), method="trf", loss=cfg.loss,
                    f_scale=cfg.f_scale, max_nfev=cfg.max_nfev, check_finite=False,
                )
        except (RuntimeError, ValueError, np.linalg.LinAlgError):
            continue
        popt = np.asarray(popt, dtype=np.float64)
        if not np.all(np.isfinite(popt)):
            continue
        sse = float(np.sum((log_rate - model(t, *popt)) ** 2))
        if math.isfinite(sse) and (best is None or sse < best[0]):
            best = (sse, popt)
    if best is None:
        return None
    sse, popt = best
    rmse = math.sqrt(sse / len(t))
    if method == EXPONENTIAL:
        return ArpsParams(method, float(popt[0]), float(popt[1]), 0.0, d_lim, 0.0), rmse
    log_qi, di, b = (float(v) for v in popt)
    return ArpsParams(method, log_qi, di, b, d_lim, switch_time(di, b, d_lim)), rmse


def fit_series(t: np.ndarray, rate: np.ndarray, method: str, cfg: ArpsConfig, warm_start: ArpsParams | None = None) -> FitResult:
    """Fit one variant to the post-peak points ``(t, rate)`` (rates positive), with the fallback chain.

    `warm_start` is the solution of the same variant at the previous origin (the caller checks that
    the peak is the same); it is tried first, together with a single default start.
    """
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; expected one of {', '.join(METHODS)}")
    t, rate = np.asarray(t, dtype=np.float64), np.asarray(rate, dtype=np.float64)
    if t.shape != rate.shape or t.ndim != 1:
        raise ValueError("t and rate must be one-dimensional arrays of the same length")
    if not np.all(rate > 0) or not np.all(np.isfinite(rate)):
        raise ValueError("the rates to fit must be positive and finite")
    d_lim = nominal_from_effective_annual(cfg.terminal_decline_effective_annual)
    log_rate = np.log(rate)

    solved = _solve(method, t, log_rate, cfg, d_lim, warm_start)
    if solved is not None:
        return FitResult(solved[0], "ok", len(t), solved[1])
    if method != EXPONENTIAL:
        solved = _solve(EXPONENTIAL, t, log_rate, cfg, d_lim, None)
        if solved is not None:
            return FitResult(solved[0], "fallback_exp", len(t), solved[1])
    return FitResult(None, "fallback_naive", len(t), float("nan"))
