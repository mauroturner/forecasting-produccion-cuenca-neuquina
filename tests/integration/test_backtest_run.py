"""The backtest task end to end on the synthetic warehouse: files, SQLite metrics, idempotence (AC13, AC22)."""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from oilgas.backtest import METHOD_CATEGORIES, POINT_METHODS, evaluation_pairs, plan_origins, run_backtest
from oilgas.config import PipelineConfig, load_config
from oilgas.warehouse import connect

BASE = load_config()


@dataclass(frozen=True)
class Ctx:
    cfg: PipelineConfig
    run_key: str


def make_ctx(warehouse: Path, interim: Path, run_key: str) -> Ctx:
    cfg = dataclasses.replace(
        BASE,
        paths=dataclasses.replace(BASE.paths, warehouse=warehouse, interim_dir=interim),
        backtest=dataclasses.replace(BASE.backtest, n_eval_origins=3, n_warmup_origins=3, n_workers=1, well_sample=20),
        ml=dataclasses.replace(BASE.ml, max_iter=8, min_samples_leaf=10, max_train_rows=2000, train_window_months=18),
    )
    return Ctx(cfg, run_key)


@pytest.fixture(scope="module")
def run(tmp_path_factory, warehouse_path):
    root = tmp_path_factory.mktemp("backtest_run")
    warehouse = root / "production.sqlite"
    shutil.copy(warehouse_path, warehouse)
    ctx = make_ctx(warehouse, root / "interim", "r-first")
    result = run_backtest(ctx)
    return ctx, result


def metrics_table(ctx: Ctx) -> pd.DataFrame:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        return pd.read_sql_query("SELECT * FROM model_backtest_metrics", conn)
    finally:
        conn.close()


def test_the_task_reports_what_it_did(run) -> None:
    ctx, result = run
    assert result["wells"] == 20
    assert len(result["origins"]["eval"]) == 3 and len(result["origins"]["warmup"]) == 3
    assert result["forecast_rows"] > 0 and 0 < result["pairs_evaluated"] <= result["forecast_rows"]
    assert result["seconds"]["total"] >= result["seconds"]["point_methods"] > 0
    names = ("point_forecasts.parquet", "ml_forecasts.parquet", "errors.parquet")
    assert set(result["files"]) == {str(Path(ctx.cfg.paths.interim_dir) / "backtest" / n) for n in names}
    assert 0 < result["ml_rows"] < result["forecast_rows"]


def test_the_intermediate_files_are_complete_and_leave_no_temporary_file(run) -> None:
    ctx, result = run
    folder = Path(ctx.cfg.paths.interim_dir) / "backtest"
    assert sorted(p.name for p in folder.iterdir()) == ["errors.parquet", "ml_forecasts.parquet", "point_forecasts.parquet"]
    forecasts = pd.read_parquet(folder / "point_forecasts.parquet")
    ml = pd.read_parquet(folder / "ml_forecasts.parquet")
    errors = pd.read_parquet(folder / "errors.parquet")
    assert len(forecasts) == len(errors) and len(forecasts) + len(ml) == result["forecast_rows"]
    assert set(forecasts["method"].astype(str)) == set(POINT_METHODS) and set(ml["method"].astype(str)) == {"ml_hgb"}
    assert {"fluid", "well_id", "origin", "horizon", "method", "age_bucket", "error"} <= set(errors.columns)
    assert forecasts["p10"].notna().any() and (forecasts["p10"].dropna() <= forecasts.loc[forecasts["p10"].notna(), "p50"]).all()
    assert ml[["p10", "p50", "p90"]].notna().all().all() and (ml["p10"] <= ml["p90"]).all()


def test_the_metrics_in_sqlite_are_the_components_of_the_evaluation_pairs(run) -> None:
    ctx, result = run
    table = metrics_table(ctx)
    assert len(table) == result["metric_rows"] > 0
    assert set(table["run_key"]) == {"r-first"} and set(table["sub_resource_type"]) <= {"SHALE", "TIGHT"}
    folder = Path(ctx.cfg.paths.interim_dir) / "backtest"
    forecasts = pd.concat([pd.read_parquet(folder / "point_forecasts.parquet"), pd.read_parquet(folder / "ml_forecasts.parquet")], ignore_index=True)
    plan = plan_origins(result["origins"]["last_index"], ctx.cfg.backtest)
    evaluation = evaluation_pairs(forecasts, plan, ctx.cfg.backtest)
    assert table["n"].sum() == len(evaluation) == result["pairs_evaluated"]
    assert table["sum_actual"].sum() == pytest.approx(evaluation["actual"].sum())
    assert table["sum_abs_error"].sum() == pytest.approx((evaluation["actual"] - evaluation["p50"]).abs().sum())
    assert (table["n_covered"] <= table["n"]).all() and (table["n_covered"] >= 0).all()
    assert (table[["sum_actual", "sum_abs_error", "sum_sq_error", "sum_pinball"]] >= 0).all().all()


def test_every_method_is_scored_on_the_same_number_of_pairs_in_each_cell(run) -> None:
    ctx, _ = run
    table = metrics_table(ctx)
    cell = ["fluid", "horizon", "origin_period_key", "age_bucket", "sub_resource_type"]
    eligible = table[table["age_bucket"] != "young"]
    counts = eligible.pivot_table(index=cell, columns="method", values="n", aggfunc="sum")
    assert set(counts.columns) == set(METHOD_CATEGORIES)
    assert counts.notna().all().all()
    assert (counts.nunique(axis=1) == 1).all()  # the six methods have the same n in every cell
    young = table[table["age_bucket"] == "young"]
    assert set(young["method"]) <= {"naive_last", "naive_mean3", "ml_hgb"} and "ml_hgb" in set(young["method"])
    young_counts = young.pivot_table(index=cell, columns="method", values="n", aggfunc="sum")
    assert young_counts.notna().all().all() and (young_counts.nunique(axis=1) == 1).all()
    horizons = set(table["horizon"])
    assert horizons <= set(ctx.cfg.backtest.eval_horizons) and 1 in horizons


def test_running_it_again_replaces_the_metrics_and_reproduces_the_files(run, tmp_path) -> None:
    ctx, _ = run
    folder = Path(ctx.cfg.paths.interim_dir) / "backtest"
    first_forecasts = pd.read_parquet(folder / "point_forecasts.parquet")
    first_ml = pd.read_parquet(folder / "ml_forecasts.parquet")
    first_metrics = metrics_table(ctx).drop(columns="run_key")
    again = run_backtest(Ctx(ctx.cfg, "r-second"))
    second = metrics_table(ctx)
    assert set(second["run_key"]) == {"r-second"} and len(second) == len(first_metrics) == again["metric_rows"]
    pd.testing.assert_frame_equal(second.drop(columns="run_key"), first_metrics)
    pd.testing.assert_frame_equal(pd.read_parquet(folder / "point_forecasts.parquet"), first_forecasts)
    pd.testing.assert_frame_equal(pd.read_parquet(folder / "ml_forecasts.parquet"), first_ml)


def test_the_task_does_not_touch_the_production_tables(run, warehouse_path) -> None:
    ctx, _ = run
    tables = ("raw_monthly_production", "stg_monthly_production", "dim_well", "fact_production_monthly")
    with sqlite3.connect(warehouse_path) as original, sqlite3.connect(ctx.cfg.paths.warehouse) as used:
        for name in tables:
            assert original.execute(f"SELECT COUNT(*) FROM {name}").fetchone() == used.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
