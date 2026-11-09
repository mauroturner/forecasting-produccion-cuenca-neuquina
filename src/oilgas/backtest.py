"""Walk-forward backtest of the point methods and their empirical bands (RF11, RF12, plan section 10).

Every method is evaluated on the same (series, origin, horizon) pairs: a series that is active at the
origin and has a row in the target month (a real zero counts). At an origin ``o`` only columns up to
``o`` of the panel are read, and the bands of that origin come from errors whose target month is not
after ``o``. The frame is long, one row per forecast:

``fluid, well_id, origin, horizon, method, segment, age_bucket, n_post_peak, target_days, actual,
p10, p50, p90, fit_status`` with volumes in the fluid's unit and ``origin`` a month index.

The wells are split into interleaved groups that worker processes fit independently; a well is always
processed whole and in origin order (so the Arps warm start is the same), and the result is sorted by
(fluid, well, origin, method, horizon): one process or many give the same frame (AC22).
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from oilgas.arps import ArpsParams, FitResult, fit_series, predict_rate
from oilgas.baselines import naive_last, naive_mean3
from oilgas.calibration import ANY_BUCKET, CELL, apply_bands, band_quantiles, log_error
from oilgas.config import ArpsConfig, BacktestConfig, PipelineConfig
from oilgas.metrics import additive_components
from oilgas.series import (
    AGE_BUCKETS,
    FLUIDS,
    SeriesPanel,
    age_bucket,
    build_panel,
    column_of,
    peak_column,
    post_peak_points,
    segment_at,
)
from oilgas.warehouse import apply_schema, connect

POINT_METHODS = ("naive_last", "naive_mean3", "arps_exp", "arps_mh_b2", "arps_mh_b1")
ML_METHOD = "ml_hgb"
METHOD_CATEGORIES = (*POINT_METHODS, ML_METHOD)
SEGMENT_CATEGORIES = ("eligible", "young")
STATUS_CATEGORIES = ("ok", "fallback_exp", "fallback_naive")
FRAME_COLUMNS = [
    "fluid", "well_id", "origin", "horizon", "method", "segment", "age_bucket", "n_post_peak",
    "target_days", "actual", "p10", "p50", "p90", "fit_status",
]
METRIC_KEYS = ["method", "fluid", "horizon", "origin_period_key", "age_bucket", "sub_resource_type"]
METRIC_COLUMNS = [
    "n", "sum_actual", "sum_p10", "sum_p50", "sum_p90", "sum_abs_error", "sum_sq_error", "sum_error", "n_covered", "sum_pinball",
]
GROUPS_PER_WORKER = 4


class RunContext(Protocol):
    """What the backtest task needs from the pipeline's run context (``oilgas.pipeline.RunContext``)."""

    cfg: PipelineConfig
    run_key: str


@dataclass(frozen=True)
class BacktestPlan:
    warmup_origins: list[int]
    eval_origins: list[int]
    last_index: int


def plan_origins(last_index: int, cfg: BacktestConfig) -> BacktestPlan:
    """Evaluation origins ``L - n_eval .. L - 1`` and the warm-up origins just before them."""
    first_eval = last_index - cfg.n_eval_origins
    return BacktestPlan(
        warmup_origins=list(range(first_eval - cfg.n_warmup_origins, first_eval)),
        eval_origins=list(range(first_eval, last_index)),
        last_index=last_index,
    )


def period_key(period_index: np.ndarray | int) -> np.ndarray | int:
    """``AAAAMM`` of a month index (``year * 12 + month - 1``)."""
    return (period_index // 12) * 100 + period_index % 12 + 1


def categorical(codes: np.ndarray, categories: Sequence[str]) -> pd.Categorical:
    return pd.Categorical.from_codes(codes, categories=list(categories))


# --- point methods ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _GroupTask:
    well_ids: np.ndarray
    rates: dict[str, np.ndarray]
    volumes: dict[str, np.ndarray]
    days: np.ndarray
    origin_cols: tuple[int, ...]
    first_index: int
    last_col: int
    methods: tuple[str, ...]
    eval_horizons: tuple[int, ...]
    all_horizon_methods: tuple[str, ...]
    max_horizon: int
    arps: ArpsConfig
    min_points: int


def _valid_horizons(rate_row: np.ndarray, col: int, task: _GroupTask) -> np.ndarray:
    """Horizons whose target month exists in the data and has a row (a month in zero has one)."""
    horizons = np.arange(1, task.max_horizon + 1)
    targets = col + horizons
    inside = targets <= task.last_col
    horizons, targets = horizons[inside], targets[inside]
    return horizons[~np.isnan(rate_row[targets])]


def _fit(method: str, fits: dict[str, FitResult], warm: dict[str, tuple[int, ArpsParams]], peak: int,
         points: tuple[np.ndarray, np.ndarray], cfg: ArpsConfig) -> FitResult:
    """Fit once per (method, origin); start from the previous origin's solution if the peak is the same."""
    if method not in fits:
        previous = warm.get(method)
        start = previous[1] if previous is not None and previous[0] == peak else None
        fits[method] = fit_series(points[0], points[1], method, cfg, start)
        if fits[method].status == "ok" and fits[method].params is not None:
            warm[method] = (peak, fits[method].params)
    return fits[method]


def _run_group(task: _GroupTask) -> dict[str, np.ndarray]:
    """Forecast every pair of a group of wells with the requested point methods (runs in a worker)."""
    meta: list[tuple] = []
    horizons: list[np.ndarray] = []
    days_list: list[np.ndarray] = []
    actual_list: list[np.ndarray] = []
    p50_list: list[np.ndarray] = []
    eval_set = set(task.eval_horizons)
    for i, well_id in enumerate(task.well_ids):
        for f_code, fluid in enumerate(FLUIDS):
            rate_row, volume_row = task.rates[fluid][i], task.volumes[fluid][i]
            warm: dict[str, tuple[int, ArpsParams]] = {}
            for col in task.origin_cols:
                segment = segment_at(rate_row, col, task.min_points)
                if segment == "inactive":
                    continue
                valid = _valid_horizons(rate_row, col, task)
                if valid.size == 0:
                    continue
                peak = peak_column(rate_row, col)
                points = post_peak_points(rate_row, col)
                n_post = points[0].size
                bucket = AGE_BUCKETS.index(age_bucket(n_post, task.min_points))
                fits: dict[str, FitResult] = {}
                for method in task.methods:
                    arps = method.startswith("arps")
                    if arps and segment == "young":
                        continue
                    hs = valid if method in task.all_horizon_methods else valid[[h in eval_set for h in valid]]
                    if hs.size == 0:
                        continue
                    target_cols = col + hs
                    target_days = task.days[target_cols].astype(np.float64)
                    status = "ok"
                    if method == "naive_last":
                        p50 = naive_last(rate_row, col, target_days)
                    elif method == "naive_mean3":
                        p50 = naive_mean3(rate_row, col, target_days)
                    else:
                        fit = _fit(method, fits, warm, peak, points, task.arps)
                        status = fit.status
                        if fit.params is None:
                            p50 = naive_mean3(rate_row, col, target_days)
                        else:
                            p50 = predict_rate(fit.params, (col - peak) + hs.astype(np.float64)) * target_days
                    meta.append((f_code, int(well_id), col + task.first_index, METHOD_CATEGORIES.index(method),
                                 SEGMENT_CATEGORIES.index(segment), bucket, n_post, STATUS_CATEGORIES.index(status)))
                    horizons.append(hs)
                    days_list.append(target_days)
                    actual_list.append(volume_row[target_cols])
                    p50_list.append(p50)
    if not meta:
        return {name: np.empty(0) for name in _GROUP_COLUMNS}
    counts = np.array([len(h) for h in horizons])
    table = np.array(meta, dtype=np.int64)
    out = {name: np.repeat(table[:, k], counts) for k, name in enumerate(_META_COLUMNS)}
    out["horizon"] = np.concatenate(horizons)
    out["target_days"] = np.concatenate(days_list)
    out["actual"] = np.concatenate(actual_list)
    out["p50"] = np.concatenate(p50_list)
    return out


_META_COLUMNS = ("fluid", "well_id", "origin", "method", "segment", "age_bucket", "n_post_peak", "fit_status")
_GROUP_COLUMNS = (*_META_COLUMNS, "horizon", "target_days", "actual", "p50")


def _frame_from_groups(groups: list[dict[str, np.ndarray]]) -> pd.DataFrame:
    parts = [g for g in groups if len(g["horizon"])]
    if not parts:
        data = {name: np.empty(0, dtype=np.int64) for name in _GROUP_COLUMNS}
        data["actual"], data["p50"] = np.empty(0), np.empty(0)
    else:
        data = {name: np.concatenate([g[name] for g in parts]) for name in _GROUP_COLUMNS}
    order = np.lexsort((data["horizon"], data["method"], data["origin"], data["well_id"], data["fluid"]))
    data = {name: values[order] for name, values in data.items()}
    n = len(data["horizon"])
    return pd.DataFrame(
        {
            "fluid": categorical(data["fluid"], FLUIDS),
            "well_id": data["well_id"].astype(np.int32),
            "origin": data["origin"].astype(np.int32),
            "horizon": data["horizon"].astype(np.int8),
            "method": categorical(data["method"], METHOD_CATEGORIES),
            "segment": categorical(data["segment"], SEGMENT_CATEGORIES),
            "age_bucket": categorical(data["age_bucket"], AGE_BUCKETS),
            "n_post_peak": data["n_post_peak"].astype(np.int16),
            "target_days": data["target_days"].astype(np.int8),
            "actual": data["actual"].astype(np.float64),
            "p10": np.full(n, np.nan),
            "p50": data["p50"].astype(np.float64),
            "p90": np.full(n, np.nan),
            "fit_status": categorical(data["fit_status"], STATUS_CATEGORIES),
        }
    )[FRAME_COLUMNS]


def run_point_methods(panel: SeriesPanel, plan: BacktestPlan, cfg: PipelineConfig, methods: Sequence[str] = POINT_METHODS) -> pd.DataFrame:
    """Forecast every pair of the plan with the point methods, in ``cfg.backtest.n_workers`` processes.

    Bands (`p10`, `p90`) are left empty: `add_empirical_bands` fills them. `methods` may be a subset.
    """
    unknown = [m for m in methods if m not in POINT_METHODS]
    if unknown:
        raise ValueError(f"unknown point method {unknown[0]!r}; expected one of {', '.join(POINT_METHODS)}")
    bt = cfg.backtest
    first = int(panel.period_index[0])
    origin_cols = tuple(column_of(panel, o) for o in [*plan.warmup_origins, *plan.eval_origins])
    last_col = min(column_of(panel, plan.last_index), len(panel.period_index) - 1)
    n_wells = len(panel.well_ids)
    n_groups = 1 if bt.n_workers == 1 else min(n_wells, bt.n_workers * GROUPS_PER_WORKER)
    tasks = []
    for k in range(max(1, n_groups)):
        rows = np.arange(n_wells)[k::max(1, n_groups)]
        if rows.size == 0:
            continue
        tasks.append(
            _GroupTask(
                well_ids=panel.well_ids[rows],
                rates={f: panel.rate[f][rows] for f in FLUIDS},
                volumes={f: panel.volume[f][rows] for f in FLUIDS},
                days=panel.days_in_month,
                origin_cols=origin_cols,
                first_index=first,
                last_col=last_col,
                methods=tuple(methods),
                eval_horizons=tuple(bt.eval_horizons),
                all_horizon_methods=tuple(bt.all_horizon_methods),
                max_horizon=bt.max_horizon,
                arps=cfg.arps,
                min_points=cfg.arps.min_post_peak_points,
            )
        )
    if bt.n_workers == 1 or len(tasks) <= 1:
        groups = [_run_group(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=bt.n_workers) as pool:
            groups = list(pool.map(_run_group, tasks))
    return _frame_from_groups(groups)


# --- bands ------------------------------------------------------------------------------------------------


def error_frame(point: pd.DataFrame, eps: float) -> pd.DataFrame:
    """Realized log error of every forecast, with the keys the calibration needs."""
    days = point["target_days"].to_numpy(dtype=np.float64)
    errors = pd.DataFrame(
        {
            "fluid": point["fluid"], "well_id": point["well_id"], "origin": point["origin"], "horizon": point["horizon"],
            "method": point["method"], "age_bucket": point["age_bucket"],
            "error": log_error(point["actual"].to_numpy() / days, point["p50"].to_numpy() / days, eps),
        }
    )
    return errors


def add_empirical_bands(point: pd.DataFrame, plan: BacktestPlan, cfg: BacktestConfig) -> pd.DataFrame:
    """Fill `p10` and `p90` of the point forecasts from the errors realized before each origin.

    The first origins have no errors yet and stay without bands; the warm-up origins exist so that the
    first evaluation origin already has errors at every horizon.
    """
    out = point.copy()
    eps = cfg.epsilon_rate
    errors = error_frame(point, eps)
    p10 = np.full(len(point), np.nan)
    p90 = np.full(len(point), np.nan)
    by_origin = point.groupby("origin", sort=True).indices
    for origin in sorted({*plan.warmup_origins, *plan.eval_origins}):
        rows = by_origin.get(origin)
        if rows is None:
            continue
        quantiles = band_quantiles(errors, origin, cfg)
        if quantiles.empty:
            continue
        keys = pd.DataFrame(
            {
                "method": point["method"].iloc[rows].astype(str).to_numpy(),
                "fluid": point["fluid"].iloc[rows].astype(str).to_numpy(),
                "horizon": point["horizon"].iloc[rows].to_numpy().astype(np.int64),
                "age_bucket": point["age_bucket"].iloc[rows].astype(str).to_numpy(),
            }
        )
        quantiles = quantiles.astype({"horizon": np.int64})
        cell = quantiles[quantiles["age_bucket"] != ANY_BUCKET][[*CELL, "age_bucket", "q10", "q90"]]
        broad = quantiles[quantiles["age_bucket"] == ANY_BUCKET][[*CELL, "q10", "q90"]].rename(columns={"q10": "b10", "q90": "b90"})
        merged = keys.merge(cell, on=[*CELL, "age_bucket"], how="left").merge(broad, on=CELL, how="left")
        q10 = merged["q10"].fillna(merged["b10"]).to_numpy()
        q90 = merged["q90"].fillna(merged["b90"]).to_numpy()
        days = point["target_days"].iloc[rows].to_numpy(dtype=np.float64)
        low, high = apply_bands(point["p50"].iloc[rows].to_numpy() / days, q10, q90, eps)
        p10[rows], p90[rows] = low * days, high * days
    out["p10"], out["p90"] = p10, p90
    return out


# --- evaluation set and metrics -----------------------------------------------------------------------------


def evaluation_pairs(frame: pd.DataFrame, plan: BacktestPlan, cfg: BacktestConfig) -> pd.DataFrame:
    """The pairs on which methods are compared: evaluation origins and horizons, with bands, for every method.

    Within a segment a pair is kept only when every method of that segment has it (a method without
    bands at that origin drops the pair for all), so each cell has the same pairs for every method.
    """
    scope = frame[frame["origin"].isin(plan.eval_origins) & frame["horizon"].isin(cfg.eval_horizons)]
    expected = scope.groupby("segment", observed=True)["method"].nunique()
    scored = scope[scope["p10"].notna() & scope["p90"].notna()]
    pair = ["segment", "fluid", "well_id", "origin", "horizon"]
    have = scored.groupby(pair, observed=True)["method"].transform("size")
    need = scored["segment"].map(expected).astype(have.dtype)
    return scored[have.to_numpy() == need.to_numpy()].reset_index(drop=True)


def backtest_metrics(evaluation: pd.DataFrame, attrs: pd.DataFrame) -> pd.DataFrame:
    """Additive components per method, fluid, horizon, origin, age bucket and sub-resource type (``model_backtest_metrics``)."""
    subtype = attrs.set_index("well_id")["sub_resource_type"]
    work = pd.DataFrame(
        {
            "method": evaluation["method"].astype(str).to_numpy(),
            "fluid": evaluation["fluid"].astype(str).to_numpy(),
            "horizon": evaluation["horizon"].to_numpy().astype(np.int64),
            "origin_period_key": period_key(evaluation["origin"].to_numpy().astype(np.int64)),
            "age_bucket": evaluation["age_bucket"].astype(str).to_numpy(),
            "sub_resource_type": evaluation["well_id"].map(subtype).fillna("UNKNOWN").astype(str).to_numpy(),
            "actual": evaluation["actual"].to_numpy(),
            "p10": evaluation["p10"].to_numpy(),
            "p50": evaluation["p50"].to_numpy(),
            "p90": evaluation["p90"].to_numpy(),
        }
    )
    return additive_components(work, METRIC_KEYS)


# --- the task -------------------------------------------------------------------------------------------------


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write to a temporary file and rename (RNF05): a failure never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def write_metrics(conn, metrics: pd.DataFrame, run_key: str) -> None:
    """Replace the content of ``model_backtest_metrics`` in one transaction."""
    columns = [*METRIC_KEYS, "run_key", *METRIC_COLUMNS]
    rows = [
        (*(row[k] for k in METRIC_KEYS), run_key, *(row[c] for c in METRIC_COLUMNS))
        for row in metrics.astype(object).to_dict("records")
    ]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM model_backtest_metrics")
        conn.executemany(
            f"INSERT INTO model_backtest_metrics ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", rows
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def run_backtest(ctx: RunContext) -> dict:
    """The ``backtest`` task: panel from the warehouse, point methods, bands, metrics to SQLite, forecasts to Parquet."""
    cfg = ctx.cfg
    started = time.perf_counter()
    conn = connect(cfg.paths.warehouse)
    try:
        apply_schema(conn)
        panel = build_panel(conn, cfg.backtest.well_sample, cfg.backtest.seed)
        plan = plan_origins(int(panel.period_index[-1]), cfg.backtest)
        t_panel = time.perf_counter()
        point = run_point_methods(panel, plan, cfg)
        t_point = time.perf_counter()
        point = add_empirical_bands(point, plan, cfg.backtest)
        t_bands = time.perf_counter()
        evaluation = evaluation_pairs(point, plan, cfg.backtest)
        metrics = backtest_metrics(evaluation, panel.attrs)
        out_dir = Path(cfg.paths.interim_dir) / "backtest"
        _write_parquet(point, out_dir / "point_forecasts.parquet")
        errors = error_frame(point, cfg.backtest.epsilon_rate)
        _write_parquet(errors, out_dir / "errors.parquet")
        write_metrics(conn, metrics, ctx.run_key)
    finally:
        conn.close()
    done = time.perf_counter()
    return {
        "wells": int(len(panel.well_ids)),
        "origins": {"warmup": plan.warmup_origins, "eval": plan.eval_origins, "last_index": plan.last_index},
        "forecast_rows": int(len(point)),
        "pairs_evaluated": int(len(evaluation)),
        "metric_rows": int(len(metrics)),
        "seconds": {"panel": t_panel - started, "point_methods": t_point - t_panel, "bands": t_bands - t_point, "total": done - started},
        "files": [str(out_dir / "point_forecasts.parquet"), str(out_dir / "errors.parquet")],
    }
