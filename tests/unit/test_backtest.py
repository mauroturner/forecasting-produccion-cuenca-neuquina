"""Walk-forward backtest of the point methods: plan, pairs, leakage, bands, determinism (AC11, AC12, AC22)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from oilgas.backtest import (
    POINT_METHODS,
    BacktestPlan,
    add_empirical_bands,
    backtest_metrics,
    evaluation_pairs,
    plan_origins,
    run_point_methods,
)
from oilgas.baselines import naive_mean3
from oilgas.config import PipelineConfig, load_config
from oilgas.metrics import coverage
from oilgas.series import SeriesPanel, column_of
from tests.fixtures.synthetic_panel import FIRST_INDEX, drop_months, perturb_after, synthetic_panel

CFG = load_config()
KEYS = ["fluid", "well_id", "origin", "horizon", "method"]


def quick_cfg(**backtest) -> PipelineConfig:
    return dataclasses.replace(CFG, backtest=dataclasses.replace(CFG.backtest, **backtest))


def plan_for(panel: SeriesPanel, n_eval: int, n_warmup: int) -> BacktestPlan:
    return plan_origins(int(panel.period_index[-1]), dataclasses.replace(CFG.backtest, n_eval_origins=n_eval, n_warmup_origins=n_warmup))


@pytest.fixture(scope="module")
def panel() -> SeriesPanel:
    return synthetic_panel(n_wells=12, n_months=48, seed=0)


@pytest.fixture(scope="module")
def plan(panel) -> BacktestPlan:
    return plan_for(panel, n_eval=4, n_warmup=3)


@pytest.fixture(scope="module")
def point(panel, plan) -> pd.DataFrame:
    return run_point_methods(panel, plan, quick_cfg(n_workers=1))


# --- the plan ---------------------------------------------------------------------------------------


def test_the_plan_has_warmup_origins_then_evaluation_origins_ending_one_month_before_the_last() -> None:
    plan = plan_origins(2000, CFG.backtest)
    assert plan.last_index == 2000
    assert plan.eval_origins == list(range(1976, 2000)) and len(plan.eval_origins) == 24
    assert plan.warmup_origins == list(range(1964, 1976)) and len(plan.warmup_origins) == 12
    small = plan_origins(500, dataclasses.replace(CFG.backtest, n_eval_origins=6, n_warmup_origins=2))
    assert small.warmup_origins == [492, 493] and small.eval_origins == [494, 495, 496, 497, 498, 499]


def test_evaluation_cells_per_horizon_shrink_as_the_horizon_grows() -> None:
    plan = plan_origins(2000, CFG.backtest)
    cells = {h: sum(1 for o in plan.eval_origins if o + h <= plan.last_index) for h in CFG.backtest.eval_horizons}
    assert cells == {1: 24, 3: 22, 6: 19, 12: 13}


# --- which pairs each method forecasts ----------------------------------------------------------------


def test_the_frame_has_the_documented_columns(point: pd.DataFrame) -> None:
    assert list(point.columns) == [
        "fluid", "well_id", "origin", "horizon", "method", "segment", "age_bucket", "n_post_peak",
        "target_days", "actual", "p10", "p50", "p90", "fit_status",
    ]
    assert not point.empty and set(point["method"].astype(str)) == set(POINT_METHODS)
    assert point["p10"].isna().all() and point["p90"].isna().all()  # the bands come later
    assert point["p50"].notna().all() and point["actual"].notna().all()
    assert (point["p50"] >= 0).all()


def test_each_method_forecasts_the_horizons_it_is_assigned(point: pd.DataFrame, panel: SeriesPanel) -> None:
    # The plan ends 7 months before the data does, so the longest horizon with a known target is 7.
    horizons = point.groupby(point["method"].astype(str))["horizon"].agg(lambda s: sorted(set(s)))
    assert horizons["arps_mh_b2"] == list(range(1, 8)) and horizons["naive_mean3"] == list(range(1, 8))
    for method in ("naive_last", "arps_exp", "arps_mh_b1"):
        assert horizons[method] == [1, 3, 6]  # the evaluation horizons that exist here
    long_panel = synthetic_panel(n_wells=6, n_months=48, seed=1, young_wells=0, with_awkward_cases=False)
    plan = plan_for(long_panel, n_eval=16, n_warmup=1)
    frame = run_point_methods(long_panel, plan, quick_cfg(n_workers=1), methods=("naive_last", "naive_mean3"))
    by_method = frame.groupby(frame["method"].astype(str))["horizon"].agg(lambda s: sorted(set(s)))
    assert by_method["naive_mean3"] == list(range(1, 13)) and by_method["naive_last"] == [1, 3, 6, 12]


def test_the_pairs_are_series_active_at_the_origin_with_a_row_in_the_target_month(point: pd.DataFrame, panel: SeriesPanel, plan: BacktestPlan) -> None:
    first = int(panel.period_index[0])
    last_col = int(plan.last_index) - first
    for row in point.sample(300, random_state=0).itertuples():
        well = int(np.searchsorted(panel.well_ids, row.well_id))
        col, target = int(row.origin) - first, int(row.origin) + int(row.horizon) - first
        assert target <= last_col and not np.isnan(panel.rate[row.fluid][well, target])
        assert panel.volume[row.fluid][well, target] == pytest.approx(row.actual)
        assert panel.days_in_month[target] == row.target_days
        assert np.nansum(panel.rate[row.fluid][well, max(0, col - 2) : col + 1] > 0) >= 1
    assert point["origin"].min() == plan.warmup_origins[0] and point["origin"].max() == plan.eval_origins[-1]


def test_a_zero_month_in_the_target_is_a_pair_but_a_missing_month_is_not(panel: SeriesPanel, plan: BacktestPlan, point: pd.DataFrame) -> None:
    first = int(panel.period_index[0])
    well0 = int(panel.well_ids[0])
    zeros = point[(point["well_id"] == well0) & (point["fluid"] == "oil") & (point["actual"] == 0)]
    assert not zeros.empty  # well 0 has two months in zero
    well1_gap = np.flatnonzero(np.isnan(panel.rate["oil"][1])[: int(plan.last_index) - first])
    gap_target = [c for c in well1_gap if panel.rate["oil"][1][c - 1] > 0]
    assert gap_target
    rows = point[(point["well_id"] == int(panel.well_ids[1])) & (point["fluid"] == "oil")]
    assert not ((rows["origin"] + rows["horizon"] - first).isin(gap_target)).any()


def test_young_series_get_only_the_baselines_and_stopped_ones_nothing(point: pd.DataFrame, panel: SeriesPanel, plan: BacktestPlan) -> None:
    young = point[point["segment"] == "young"]
    assert not young.empty and set(young["method"].astype(str)) == {"naive_last", "naive_mean3"}
    assert set(point[point["segment"] == "eligible"]["method"].astype(str)) == set(POINT_METHODS)
    assert set(point["segment"].astype(str)) == {"eligible", "young"}  # an inactive series is never a pair
    stopped = int(panel.well_ids[2])  # stops reporting four months before the end
    last_origin_of_stopped = point[point["well_id"] == stopped]["origin"].max()
    assert last_origin_of_stopped < plan.eval_origins[-1] - 1


def test_every_method_has_the_same_pairs_in_the_evaluation_horizons(point: pd.DataFrame) -> None:
    eligible = point[(point["segment"] == "eligible") & point["horizon"].isin([1, 3, 6, 12])]
    pairs = {m: set(zip(g["fluid"], g["well_id"], g["origin"], g["horizon"], strict=True)) for m, g in eligible.groupby(eligible["method"].astype(str))}
    assert len(pairs) == 5 and all(p == pairs["naive_last"] for p in pairs.values())


def test_baseline_forecasts_are_the_baseline_functions_applied_at_the_origin(point: pd.DataFrame, panel: SeriesPanel) -> None:
    first = int(panel.period_index[0])
    rows = point[point["method"] == "naive_mean3"].sample(100, random_state=1)
    for row in rows.itertuples():
        well, col = int(np.searchsorted(panel.well_ids, row.well_id)), int(row.origin) - first
        target_days = panel.days_in_month[col + int(row.horizon)]
        want = naive_mean3(panel.rate[row.fluid][well], col, np.array([target_days]))[0]
        assert row.p50 == pytest.approx(want)


def test_arps_rows_report_how_each_curve_was_fitted(point: pd.DataFrame) -> None:
    arps = point[point["method"].astype(str).str.startswith("arps")]
    assert set(arps["fit_status"].astype(str)) <= {"ok", "fallback_exp", "fallback_naive"}
    assert (arps["fit_status"] == "ok").mean() > 0.9
    assert set(point[point["method"].astype(str).str.startswith("naive")]["fit_status"].astype(str)) == {"ok"}


def test_a_failed_curve_forecasts_like_naive_mean3(monkeypatch: pytest.MonkeyPatch) -> None:
    from oilgas import arps as arps_module

    def always_fails(*args, **kwargs):
        raise RuntimeError("Optimal parameters not found")

    monkeypatch.setattr(arps_module, "curve_fit", always_fails)
    panel = synthetic_panel(n_wells=4, n_months=36, seed=2, young_wells=0, with_awkward_cases=False)
    plan = plan_for(panel, n_eval=2, n_warmup=1)
    frame = run_point_methods(panel, plan, quick_cfg(n_workers=1), methods=("naive_mean3", "arps_mh_b2"))
    key = ["fluid", "well_id", "origin", "horizon"]
    arps = frame[frame["method"] == "arps_mh_b2"].set_index(key)
    naive = frame[frame["method"] == "naive_mean3"].set_index(key)
    assert (arps["fit_status"] == "fallback_naive").all()
    assert np.array_equal(arps["p50"].to_numpy(), naive.loc[arps.index, "p50"].to_numpy())


# --- no leakage (AC11) ------------------------------------------------------------------------------------


@pytest.mark.parametrize("keep_gaps", [True, False])
def test_scrambling_everything_after_an_origin_changes_no_forecast_made_at_or_before_it(panel: SeriesPanel, keep_gaps: bool) -> None:
    plan = plan_for(panel, n_eval=5, n_warmup=3)
    cfg = quick_cfg(n_workers=1)
    test_origin = plan.eval_origins[2]
    cut = column_of(panel, test_origin)
    base = add_empirical_bands(run_point_methods(panel, plan, cfg), plan, cfg.backtest)
    changed_panel = perturb_after(panel, cut, keep_gaps=keep_gaps)
    assert not np.array_equal(changed_panel.volume["oil"], panel.volume["oil"], equal_nan=True)
    changed = add_empirical_bands(run_point_methods(changed_panel, plan, cfg), plan, cfg.backtest)

    def at_or_before(frame: pd.DataFrame) -> pd.DataFrame:
        part = frame[frame["origin"] <= test_origin].copy()
        for key in ("fluid", "method", "segment", "age_bucket", "fit_status"):
            part[key] = part[key].astype(str)
        return part.set_index(KEYS).sort_index()

    a, b = at_or_before(base), at_or_before(changed)
    common = a.index.intersection(b.index)
    assert len(common) > 0.8 * len(a)  # with `keep_gaps` all of them; otherwise the pairs with a target row in both
    for column in ("p50", "p10", "p90", "n_post_peak", "target_days"):
        assert np.array_equal(a.loc[common, column].to_numpy(), b.loc[common, column].to_numpy(), equal_nan=True), column
    for column in ("segment", "age_bucket", "fit_status"):
        assert (a.loc[common, column] == b.loc[common, column]).all(), column
    if keep_gaps:
        assert len(common) == len(a) == len(b)
        assert not np.array_equal(a["actual"].to_numpy(), b["actual"].to_numpy())  # the targets did change


def test_deleting_the_rows_after_an_origin_that_follows_a_month_without_rows_changes_no_forecast_at_it() -> None:
    """The evaluator's finding (B1): whether an origin was fitted must not depend on what comes after a later origin."""
    base = synthetic_panel(n_wells=14, n_months=48, seed=3, young_wells=0, with_awkward_cases=False)
    plan = plan_for(base, n_eval=14, n_warmup=0)  # origins 33..46
    origin = plan.eval_origins[1]  # 34: its own month has no row in either panel
    col = column_of(base, origin)
    cfg = quick_cfg(n_workers=1)
    full = drop_months(base, [col])  # the previous origin, 33, still has targets 35..45 here
    later_deleted = drop_months(base, range(col, col + 12))  # 33 has no target left; 34 keeps only month 46 (horizon 12)
    a = run_point_methods(full, plan, cfg).query("origin == @origin")
    b = run_point_methods(later_deleted, plan, cfg).query("origin == @origin")
    assert set(b["horizon"]) == {12} and set(a["horizon"]) > {12}
    a, b = (f.assign(**{k: f[k].astype(str) for k in ("fluid", "method")}).set_index(KEYS).sort_index() for f in (a, b))
    common = b.index
    assert len(common) > 20
    assert np.array_equal(a.loc[common, "p50"].to_numpy(), b.loc[common, "p50"].to_numpy())
    assert (a.loc[common, "fit_status"].astype(str) == b.loc[common, "fit_status"].astype(str)).all()


def test_the_bands_at_an_origin_use_only_errors_whose_target_is_not_after_it(panel: SeriesPanel) -> None:
    plan = plan_for(panel, n_eval=4, n_warmup=4)
    cfg = quick_cfg(n_workers=1)
    frame = run_point_methods(panel, plan, cfg, methods=("naive_last", "naive_mean3"))
    banded = add_empirical_bands(frame, plan, cfg.backtest)
    origin = plan.eval_origins[1]
    # Wreck the actuals of every pair whose target is after that origin: bands at the origin must not move.
    wrecked = frame.copy()
    later = wrecked["origin"] + wrecked["horizon"] > origin
    wrecked.loc[later, "actual"] = wrecked.loc[later, "actual"] * 7 + 1000
    again = add_empirical_bands(wrecked, plan, cfg.backtest)
    mask = frame["origin"] == origin
    assert np.array_equal(banded.loc[mask, "p10"].to_numpy(), again.loc[mask, "p10"].to_numpy(), equal_nan=True)
    assert np.array_equal(banded.loc[mask, "p90"].to_numpy(), again.loc[mask, "p90"].to_numpy(), equal_nan=True)
    assert banded.loc[mask, "p10"].notna().any()


# --- bands and coverage (AC12) -----------------------------------------------------------------------------


def test_bands_surround_the_median_and_leave_it_alone(point: pd.DataFrame, plan: BacktestPlan) -> None:
    banded = add_empirical_bands(point, plan, quick_cfg().backtest)
    has_bands = banded.dropna(subset=["p10", "p90"])
    horizon_one = banded[banded["origin"].isin(plan.eval_origins) & (banded["horizon"] == 1)]
    assert len(horizon_one) > 0 and horizon_one["p10"].notna().all() and horizon_one["p90"].notna().all()
    assert (has_bands["p10"] <= has_bands["p50"]).all() and (has_bands["p50"] <= has_bands["p90"]).all()
    assert (has_bands["p10"] >= 0).all()
    assert np.array_equal(banded["p50"].to_numpy(), point["p50"].to_numpy())
    first_origin = banded[banded["origin"] == plan.warmup_origins[0]]
    assert first_origin["p10"].isna().all()  # nothing has been realized before the first origin


def test_empirical_bands_cover_about_eighty_percent_on_300_synthetic_wells() -> None:
    panel = synthetic_panel(n_wells=300, n_months=60, seed=11, young_wells=30, with_awkward_cases=False)
    cfg = quick_cfg(n_workers=1)
    plan = plan_for(panel, n_eval=12, n_warmup=12)
    frame = run_point_methods(panel, plan, cfg, methods=("naive_last", "naive_mean3"))
    frame = add_empirical_bands(frame, plan, cfg.backtest)
    evaluated = frame[frame["origin"].isin(plan.eval_origins)].dropna(subset=["p10"])
    for method in ("naive_last", "naive_mean3"):
        for horizon in (1, 3):
            part = evaluated[(evaluated["method"] == method) & (evaluated["horizon"] == horizon)]
            assert len(part) > 3000
            assert coverage(part["actual"], part["p10"], part["p90"]) == pytest.approx(0.80, abs=0.04), (method, horizon)


def test_the_bands_of_the_arps_curves_are_sane_too() -> None:
    panel = synthetic_panel(n_wells=40, n_months=48, seed=5, young_wells=4, with_awkward_cases=False)
    cfg = quick_cfg(n_workers=1, eval_horizons=(1, 3))
    plan = plan_for(panel, n_eval=4, n_warmup=4)
    frame = add_empirical_bands(run_point_methods(panel, plan, cfg, methods=("arps_mh_b2",)), plan, cfg.backtest)
    evaluated = frame[frame["origin"].isin(plan.eval_origins) & frame["horizon"].isin([1, 3])].dropna(subset=["p10"])
    assert len(evaluated) > 200
    assert 0.65 <= coverage(evaluated["actual"], evaluated["p10"], evaluated["p90"]) <= 0.92


# --- determinism (AC22) ------------------------------------------------------------------------------------


def test_one_and_two_processes_give_the_same_frame(panel: SeriesPanel, plan: BacktestPlan) -> None:
    methods = ("naive_last", "naive_mean3", "arps_mh_b2")
    one = run_point_methods(panel, plan, quick_cfg(n_workers=1), methods=methods)
    two = run_point_methods(panel, plan, quick_cfg(n_workers=2), methods=methods)
    pd.testing.assert_frame_equal(one, two)
    cfg = quick_cfg()
    pd.testing.assert_frame_equal(add_empirical_bands(one, plan, cfg.backtest), add_empirical_bands(two, plan, cfg.backtest))


def test_the_frame_is_sorted_by_fluid_well_origin_method_horizon(point: pd.DataFrame) -> None:
    order = {m: i for i, m in enumerate(POINT_METHODS)}
    key = pd.DataFrame(
        {
            "fluid": point["fluid"].astype(str).map({"oil": 0, "gas": 1}),
            "well": point["well_id"], "origin": point["origin"],
            "method": point["method"].astype(str).map(order), "horizon": point["horizon"],
        }
    )
    assert key.equals(key.sort_values(list(key.columns), kind="stable").reset_index(drop=True))


# --- the evaluation set and the metrics table --------------------------------------------------------------


def evaluation_input() -> pd.DataFrame:
    cols = ["fluid", "well_id", "origin", "horizon", "method", "segment", "age_bucket", "n_post_peak", "target_days",
            "actual", "p10", "p50", "p90", "fit_status"]
    rows = []

    def add(well, origin, horizon, methods, segment="eligible", p10=4.0):
        for method in methods:
            band = np.nan if (well == 4 and method == "c") else p10
            rows.append(("oil", well, origin, horizon, method, segment, "12-23" if segment == "eligible" else "young", 12, 30,
                         10.0, band, 11.0, 15.0, "ok"))

    add(1, 10, 1, "abc")  # kept: every method of the eligible segment has it
    add(2, 10, 1, "ab")  # dropped: method c has no row for this pair
    add(4, 10, 1, "abc")  # dropped: method c has no bands yet, so it cannot be scored
    add(1, 10, 2, "abc")  # dropped: horizon 2 is not an evaluation horizon
    add(1, 5, 1, "abc")  # dropped: a warm-up origin only calibrates
    add(3, 10, 1, "ab", segment="young")  # kept: the young segment is only forecast by a and b
    return pd.DataFrame(rows, columns=cols)


def test_the_evaluation_set_keeps_the_same_pairs_for_every_method_of_a_segment() -> None:
    plan = BacktestPlan(warmup_origins=[5], eval_origins=[10], last_index=20)
    out = evaluation_pairs(evaluation_input(), plan, dataclasses.replace(CFG.backtest, eval_horizons=(1,)))
    assert len(out) == 5
    eligible, young = out[out["segment"] == "eligible"], out[out["segment"] == "young"]
    assert set(eligible["well_id"]) == {1} and sorted(eligible["method"].astype(str)) == ["a", "b", "c"]
    assert set(young["well_id"]) == {3} and sorted(young["method"].astype(str)) == ["a", "b"]
    assert set(out["origin"]) == {10} and set(out["horizon"]) == {1} and out["p10"].notna().all()


def test_the_metrics_table_has_the_grain_of_model_backtest_metrics(point: pd.DataFrame, panel: SeriesPanel, plan: BacktestPlan) -> None:
    cfg = quick_cfg()
    banded = add_empirical_bands(point, plan, cfg.backtest)
    evaluation = evaluation_pairs(banded, plan, cfg.backtest)
    metrics = backtest_metrics(evaluation, panel.attrs)
    grain = ["method", "fluid", "horizon", "origin_period_key", "age_bucket", "sub_resource_type"]
    assert not metrics.duplicated(grain).any()
    assert {"n", "sum_actual", "sum_p10", "sum_p50", "sum_p90", "sum_abs_error", "sum_sq_error", "sum_error", "n_covered", "sum_pinball"} <= set(metrics.columns)
    assert metrics["n"].sum() == len(evaluation) and metrics["sum_actual"].sum() == pytest.approx(evaluation["actual"].sum())
    assert set(metrics["sub_resource_type"]) == {"SHALE", "TIGHT"}
    keys = metrics["origin_period_key"].unique()
    assert all(1 <= k % 100 <= 12 and 2018 <= k // 100 <= 2022 for k in keys)  # AAAAMM, not a month index
    last = plan.eval_origins[-1]
    assert (last // 12) * 100 + last % 12 + 1 in keys
    young = metrics[metrics["age_bucket"] == "young"]
    assert set(young["method"].astype(str)) <= {"naive_last", "naive_mean3"}
    assert FIRST_INDEX < plan.eval_origins[0]
