"""The production forecast at the last published month (RF16, plan section 12) on the synthetic warehouse."""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oilgas.arps import fit_series, predict_rate
from oilgas.backtest import run_backtest
from oilgas.config import PipelineConfig, load_config
from oilgas.forecast import run_production_forecast
from oilgas.series import build_panel, peak_column, post_peak_points, segment_at
from oilgas.warehouse import connect

BASE = load_config()
LAST = 202412  # the last month of the synthetic publication
HORIZONS = list(range(1, 13))


@dataclass(frozen=True)
class Ctx:
    cfg: PipelineConfig
    run_key: str


def make_ctx(warehouse: Path, interim: Path, run_key: str) -> Ctx:
    cfg = dataclasses.replace(
        BASE,
        paths=dataclasses.replace(BASE.paths, warehouse=warehouse, interim_dir=interim),
        backtest=dataclasses.replace(BASE.backtest, n_eval_origins=6, n_warmup_origins=6, n_workers=1, well_sample=20),
        ml=dataclasses.replace(BASE.ml, max_iter=8, min_samples_leaf=10, max_train_rows=2000, train_window_months=18),
    )
    return Ctx(cfg, run_key)


@pytest.fixture(scope="module")
def forecast(tmp_path_factory, warehouse_path):
    root = tmp_path_factory.mktemp("forecast_run")
    warehouse = root / "production.sqlite"
    shutil.copy(warehouse_path, warehouse)
    ctx = make_ctx(warehouse, root / "interim", "r-backtest")
    run_backtest(ctx)
    result = run_production_forecast(Ctx(ctx.cfg, "r-forecast"))
    return ctx, result


def table(ctx: Ctx, name: str) -> pd.DataFrame:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        return pd.read_sql_query(f"SELECT * FROM {name}", conn)
    finally:
        conn.close()


def panel_of(ctx: Ctx):
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        return build_panel(conn, ctx.cfg.backtest.well_sample, ctx.cfg.backtest.seed)
    finally:
        conn.close()


def segments(ctx: Ctx, fluid: str) -> dict[int, str]:
    panel = panel_of(ctx)
    col = len(panel.period_index) - 1
    return {int(w): segment_at(panel.rate[fluid][i], col, ctx.cfg.arps.min_post_peak_points) for i, w in enumerate(panel.well_ids)}


# --- what the task writes -------------------------------------------------------------------------------------


def test_the_task_reports_the_origin_and_what_it_wrote(forecast) -> None:
    ctx, result = forecast
    rows = table(ctx, "model_forecast")
    assert result["origin_period_key"] == LAST
    assert result["forecast_rows"] == len(rows) > 0
    assert result["rows_without_bands"] == 0
    assert result["fit_rows"] == len(table(ctx, "model_fit")) > 0
    assert result["curve_rows"] == len(table(ctx, "model_fitted_curve")) > 0
    assert set(result["series"]) == {"eligible", "young"} and result["seconds"]["total"] > 0


def test_every_active_series_is_forecast_with_the_methods_of_its_segment_for_twelve_months(forecast) -> None:
    ctx, _ = forecast
    rows = table(ctx, "model_forecast")
    assert set(rows["origin_period_key"]) == {LAST} and set(rows["run_key"]) == {"r-forecast"}
    for fluid in ("oil", "gas"):
        for well, segment in segments(ctx, fluid).items():
            mine = rows[(rows["well_id"] == well) & (rows["fluid"] == fluid)]
            if segment == "inactive":
                assert mine.empty
                continue
            expected = {"arps_mh_b2", "naive_mean3", "ml_hgb"} if segment == "eligible" else {"naive_mean3", "ml_hgb"}
            assert set(mine["method"]) == expected, (well, fluid, segment)
            assert set(mine["segment"]) == {segment}
            for method in expected:
                assert sorted(mine[mine["method"] == method]["horizon"]) == HORIZONS
    assert {"eligible", "young"} <= set(rows["segment"])


def test_targets_bands_and_companies_follow_the_contract(forecast) -> None:
    ctx, _ = forecast
    rows = table(ctx, "model_forecast")
    month = (rows["horizon"] - 1 + 12) % 12 + 1  # December + h
    year = 2024 + (rows["horizon"] + 11) // 12
    assert (rows["target_period_key"] == year * 100 + month).all()
    assert rows[["p10", "p50", "p90"]].notna().all().all()
    assert (rows["p10"] >= 0).all() and (rows["p10"] <= rows["p50"]).all() and (rows["p50"] <= rows["p90"]).all()
    assert rows["company_code"].isin(["YPF", "VISTA", "PAE", "TECP", "SHEL", "PLUS"]).all()
    assert set(rows["fit_status"]) <= {"ok", "fallback_exp", "fallback_naive"}
    assert (rows[rows["method"] != "arps_mh_b2"]["fit_status"] == "ok").all()


def test_the_operator_is_the_one_at_the_origin(forecast, fixture_truth, valid_frame) -> None:
    ctx, _ = forecast
    rows = table(ctx, "model_forecast")
    last = valid_frame[valid_frame["period_key"] == LAST].set_index("well_id")["company_code"]
    for well in rows["well_id"].unique():
        if well in last.index:
            assert set(rows[rows["well_id"] == well]["company_code"]) == {last[well]}


def test_exactly_the_method_chosen_by_the_backtest_is_selected(forecast) -> None:
    ctx, _ = forecast
    rows = table(ctx, "model_forecast")
    selection = table(ctx, "model_selection")
    chosen = {(r.fluid, r.segment): r.method for r in selection.itertuples()}
    assert rows["is_selected"].isin([0, 1]).all()
    for r in rows.itertuples():
        assert bool(r.is_selected) == (chosen.get((r.fluid, r.segment)) == r.method), r
    per_series = rows[rows["is_selected"] == 1].groupby(["well_id", "fluid", "horizon"]).size()
    assert (per_series == 1).all()


def test_the_point_forecasts_are_the_curve_and_the_average_of_the_last_three_months(forecast) -> None:
    ctx, _ = forecast
    rows = table(ctx, "model_forecast")
    panel = panel_of(ctx)
    col = len(panel.period_index) - 1
    cfg = ctx.cfg
    checked = 0
    for fluid in ("oil", "gas"):
        for i, well in enumerate(panel.well_ids):
            rate = panel.rate[fluid][i]
            if segment_at(rate, col, cfg.arps.min_post_peak_points) != "eligible":
                continue
            t, y = post_peak_points(rate, col)
            fit = fit_series(t, y, "arps_mh_b2", cfg.arps)
            peak = peak_column(rate, col)
            mine = rows[(rows["well_id"] == well) & (rows["fluid"] == fluid)].set_index(["method", "horizon"])
            for h in HORIZONS:
                days = (pd.Period("2024-12") + h).days_in_month
                assert mine.loc[("naive_mean3", h), "p50"] == pytest.approx(np.nanmean(rate[col - 2 : col + 1]) * days)
                if fit.status == "ok":
                    curve = float(predict_rate(fit.params, np.array([float(col - peak + h)]))[0]) * days
                    assert mine.loc[("arps_mh_b2", h), "p50"] == pytest.approx(curve)
                    assert mine.loc[("arps_mh_b2", h), "fit_status"] == "ok"
            checked += 1
    assert checked > 5


def test_the_bands_of_the_point_methods_come_from_the_realized_errors_of_the_backtest(forecast, tmp_path) -> None:
    ctx, _ = forecast
    errors_path = Path(ctx.cfg.paths.interim_dir) / "backtest" / "errors.parquet"
    errors = pd.read_parquet(errors_path)
    shifted = errors.assign(error=errors["error"].astype(float) + 1.0)  # every past forecast was a lot too low
    root = tmp_path / "shifted"
    (root / "interim" / "backtest").mkdir(parents=True)
    shifted.to_parquet(root / "interim" / "backtest" / "errors.parquet", index=False)
    warehouse = root / "production.sqlite"
    shutil.copy(ctx.cfg.paths.warehouse, warehouse)
    moved = Ctx(dataclasses.replace(ctx.cfg, paths=dataclasses.replace(ctx.cfg.paths, warehouse=warehouse, interim_dir=root / "interim")), "r-shifted")
    run_production_forecast(moved)
    before = table(ctx, "model_forecast")
    after = table(moved, "model_forecast")
    key = ["well_id", "fluid", "method", "horizon"]
    merged = before.merge(after, on=key, suffixes=("_a", "_b"))
    naive = merged[merged["method"] == "naive_mean3"]
    assert len(naive) > 0
    assert (naive["p90_b"] > naive["p90_a"]).any()  # a wider upper band when the past errors were larger
    assert np.allclose(naive["p50_a"], naive["p50_b"])  # the median does not move
    assert np.allclose(naive["p10_b"], naive["p50_b"])  # errors all positive: the lower quantile is clipped at the median (D29)
    ml = merged[merged["method"] == "ml_hgb"]
    assert np.allclose(ml[["p10_a", "p50_a", "p90_a"]].to_numpy(), ml[["p10_b", "p50_b", "p90_b"]].to_numpy())  # the ML bands are its own


def test_each_eligible_series_has_the_three_arps_variants_in_model_fit(forecast) -> None:
    ctx, _ = forecast
    fits = table(ctx, "model_fit")
    assert set(fits["origin_period_key"]) == {LAST} and set(fits["run_key"]) == {"r-forecast"}
    for fluid in ("oil", "gas"):
        for well, segment in segments(ctx, fluid).items():
            mine = fits[(fits["well_id"] == well) & (fits["fluid"] == fluid)]
            if segment == "eligible":
                assert sorted(mine["method"]) == ["arps_exp", "arps_mh_b1", "arps_mh_b2"]
            else:
                assert mine.empty
    ok = fits[fits["status"] == "ok"]
    assert np.allclose(ok["qi_rate_per_day"], np.exp(ok["log_qi"])) and (ok["n_points"] >= ctx.cfg.arps.min_post_peak_points).all()
    assert ok["di_nominal_per_month"].gt(0).all() and ok["d_effective_annual_initial"].between(0, 1).all()
    assert fits["peak_period_key"].between(201801, LAST).all()
    naive = fits[fits["status"] == "fallback_naive"]
    assert naive[["log_qi", "di_nominal_per_month", "b"]].isna().all().all()


def test_the_fitted_curve_covers_the_months_from_the_peak_to_the_origin(forecast) -> None:
    ctx, _ = forecast
    curve = table(ctx, "model_fitted_curve")
    fits = table(ctx, "model_fit")
    assert set(curve["origin_period_key"]) == {LAST} and set(curve["fluid"]) == {"oil", "gas"}
    assert (curve["fitted_volume"] > 0).all()
    one = curve.groupby(["well_id", "fluid"]).get_group(next(iter(curve.groupby(["well_id", "fluid"]).groups)))
    peak = int(fits[(fits["well_id"] == one["well_id"].iloc[0]) & (fits["fluid"] == one["fluid"].iloc[0]) & (fits["method"] == "arps_mh_b2")]["peak_period_key"].iloc[0])
    months = sorted(one["period_key"])
    assert months[0] == peak and months[-1] == LAST  # peak to origin, one row per calendar month
    assert len(months) == (LAST // 100 - peak // 100) * 12 + (LAST % 100 - peak % 100) + 1


# --- repetition and accumulation --------------------------------------------------------------------------------


def test_running_the_same_origin_again_replaces_its_rows_and_keeps_other_origins(forecast) -> None:
    ctx, result = forecast
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        conn.execute(
            "INSERT INTO model_forecast (origin_period_key, well_id, fluid, method, horizon, run_key, target_period_key, p10, p50, p90, is_selected) "
            "VALUES (202401, 1, 'oil', 'naive_mean3', 1, 'old', 202402, 1, 2, 3, 0)"
        )
        conn.execute(
            "INSERT INTO model_fit (origin_period_key, well_id, fluid, method, run_key) VALUES (202401, 1, 'oil', 'arps_mh_b2', 'old')"
        )
    finally:
        conn.close()
    first = table(ctx, "model_forecast")
    again = run_production_forecast(Ctx(ctx.cfg, "r-again"))
    rows = table(ctx, "model_forecast")
    assert again["forecast_rows"] == result["forecast_rows"]
    current = rows[rows["origin_period_key"] == LAST]
    assert len(current) == result["forecast_rows"] and set(current["run_key"]) == {"r-again"}
    pd.testing.assert_frame_equal(
        current.drop(columns="run_key").reset_index(drop=True),
        first[first["origin_period_key"] == LAST].drop(columns="run_key").reset_index(drop=True),
    )
    assert rows[rows["origin_period_key"] == 202401]["run_key"].tolist() == ["old"]
    assert table(ctx, "model_fit")["origin_period_key"].value_counts().to_dict()[202401] == 1
    assert set(table(ctx, "model_fitted_curve")["origin_period_key"]) == {LAST}  # the curve keeps only the latest origin


def test_it_does_not_touch_the_backtest_tables(forecast) -> None:
    ctx, _ = forecast
    metrics = table(ctx, "model_backtest_metrics")
    assert set(metrics["run_key"]) == {"r-backtest"} and len(metrics) > 0
    assert set(table(ctx, "model_summary")["run_key"]) == {"r-backtest"}


# --- what it needs ----------------------------------------------------------------------------------------------


def test_without_the_backtest_errors_it_says_to_run_the_backtest(forecast, tmp_path) -> None:
    ctx, _ = forecast
    warehouse = tmp_path / "production.sqlite"
    shutil.copy(ctx.cfg.paths.warehouse, warehouse)
    lonely = Ctx(dataclasses.replace(ctx.cfg, paths=dataclasses.replace(ctx.cfg.paths, warehouse=warehouse, interim_dir=tmp_path / "none")), "r-x")
    with pytest.raises(FileNotFoundError, match="backtest"):
        run_production_forecast(lonely)


def test_without_a_method_selection_it_says_to_run_the_backtest(forecast, tmp_path) -> None:
    ctx, _ = forecast
    warehouse = tmp_path / "production.sqlite"
    shutil.copy(ctx.cfg.paths.warehouse, warehouse)
    with sqlite3.connect(warehouse) as conn:
        conn.execute("DELETE FROM model_selection")
    bare = Ctx(dataclasses.replace(ctx.cfg, paths=dataclasses.replace(ctx.cfg.paths, warehouse=warehouse)), "r-x")
    with pytest.raises(ValueError, match="backtest"):
        run_production_forecast(bare)
    with sqlite3.connect(warehouse) as conn:
        assert conn.execute("SELECT COUNT(*) FROM model_forecast WHERE run_key = 'r-x'").fetchone()[0] == 0
