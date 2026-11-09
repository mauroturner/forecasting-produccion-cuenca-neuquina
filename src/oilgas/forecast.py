"""Production forecast at the last published month (RF16, plan section 12).

For every series active at the last month ``L``: an eligible one gets ``arps_mh_b2`` (with its fallback
chain), ``naive_mean3`` and ``ml_hgb``; a young one gets ``naive_mean3`` and ``ml_hgb``; each for the next
12 months with P10/P50/P90. The bands of the point methods come from the errors the backtest realized
(the 12 most recent origins whose target is not after ``L``); those of ``ml_hgb`` from its quantile models,
trained on targets not after ``L``. The three Arps variants are also stored with their parameters
(``model_fit``) and the base curve over the fitted months (``model_fitted_curve``). ``is_selected`` marks
the method the backtest chose for the segment (``model_selection``).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from oilgas.arps import METHODS as ARPS_METHODS
from oilgas.arps import effective_annual_initial, fit_series, predict_rate
from oilgas.backtest import RunContext, bands_at_origin, period_key
from oilgas.baselines import naive_mean3
from oilgas.features import base_rate, features_at, training_examples
from oilgas.ml import fit_quantile_models, predict_volumes
from oilgas.reporting import read_selection
from oilgas.fracture import model_panel
from oilgas.series import FLUIDS, SeriesPanel, age_bucket, days_in_months, peak_column, post_peak_points, segment_at
from oilgas.warehouse import apply_schema, connect

logger = logging.getLogger(__name__)

BASE_ARPS = "arps_mh_b2"
ML_METHOD = "ml_hgb"
NAIVE = "naive_mean3"
FORECAST_COLUMNS = [
    "origin_period_key", "well_id", "fluid", "method", "horizon", "run_key", "target_period_key", "company_code",
    "p10", "p50", "p90", "segment", "is_selected", "fit_status",
]
FIT_COLUMNS = [
    "origin_period_key", "well_id", "fluid", "method", "run_key", "peak_period_key", "log_qi", "qi_rate_per_day",
    "di_nominal_per_month", "b", "d_lim_nominal_per_month", "t_switch_months", "d_effective_annual_initial", "n_points",
    "rmse_log", "status",
]
CURVE_COLUMNS = ["origin_period_key", "well_id", "fluid", "period_key", "fitted_volume"]


def _errors_path(interim_dir: Path) -> Path:
    return Path(interim_dir) / "backtest" / "errors.parquet"


def _load_errors(interim_dir: Path) -> pd.DataFrame:
    path = _errors_path(interim_dir)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: run the backtest task before the forecast (it writes the errors the bands need)")
    return pd.read_parquet(path)


def _none_if_nan(value):
    return None if value is None or (isinstance(value, float) and not np.isfinite(value)) else value


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[tuple]:
    """Python tuples SQLite can bind (no numpy scalars), missing values as None."""
    lists = [[_none_if_nan(v) for v in frame[c].tolist()] for c in columns]
    return list(zip(*lists, strict=True))


class _Collected:
    """What the loop over the series of one fluid gathers before it becomes frames."""

    def __init__(self) -> None:
        self.meta: list[tuple] = []  # (panel row, segment, age bucket, method, fit status)
        self.p50: list[np.ndarray] = []
        self.fits: list[dict] = []
        self.curves: list[dict] = []
        self.counts = {"eligible": 0, "young": 0, "inactive": 0}


def _fit_row(origin_key: int, well: int, fluid: str, variant: str, run_key: str, peak_key: int, n_points: int, fit) -> dict:
    """One ``model_fit`` row; the parameters stay empty when every start failed (``fallback_naive``)."""
    row = dict.fromkeys(FIT_COLUMNS)
    row.update(
        origin_period_key=origin_key, well_id=well, fluid=fluid, method=variant, run_key=run_key, peak_period_key=peak_key,
        n_points=n_points, rmse_log=fit.rmse_log, status=fit.status,
    )
    params = fit.params
    if params is not None:
        row.update(
            log_qi=params.log_qi, qi_rate_per_day=float(np.exp(params.log_qi)), di_nominal_per_month=params.di, b=params.b,
            d_lim_nominal_per_month=params.d_lim, t_switch_months=params.t_switch,
            d_effective_annual_initial=effective_annual_initial(params),
        )
    return row


def _point_methods(panel: SeriesPanel, fluid: str, col: int, horizons: np.ndarray, cfg, origin_key: int, run_key: str) -> _Collected:
    """Naive average for every active series; Arps (three variants, base forecast) for the eligible ones."""
    rate = panel.rate[fluid]
    target_days = days_in_months(int(panel.period_index[col]) + horizons).astype(np.float64)
    min_points = cfg.arps.min_post_peak_points
    out = _Collected()
    for i, well in enumerate(panel.well_ids):
        segment = segment_at(rate[i], col, min_points)
        out.counts[segment] += 1
        if segment == "inactive":
            continue
        t, y = post_peak_points(rate[i], col)
        bucket = age_bucket(t.size, min_points)
        mean3 = naive_mean3(rate[i], col, target_days)
        out.meta.append((i, segment, bucket, NAIVE, "ok"))
        out.p50.append(mean3)
        if segment != "eligible":
            continue
        peak = peak_column(rate[i], col)
        peak_key = int(period_key(int(panel.period_index[peak])))
        fits = {variant: fit_series(t, y, variant, cfg.arps) for variant in ARPS_METHODS}
        for variant, fit in fits.items():
            out.fits.append(_fit_row(origin_key, int(well), fluid, variant, run_key, peak_key, t.size, fit))
        base = fits[BASE_ARPS]
        if base.params is None:  # every start failed: the naive average stands in, and the status says so
            out.meta.append((i, segment, bucket, BASE_ARPS, base.status))
            out.p50.append(mean3)
            continue
        out.meta.append((i, segment, bucket, BASE_ARPS, base.status))
        out.p50.append(predict_rate(base.params, float(col - peak) + horizons) * target_days)
        months = np.arange(0, col - peak + 1)
        volume = predict_rate(base.params, months.astype(np.float64)) * panel.days_in_month[peak : col + 1]
        out.curves.extend(
            {"origin_period_key": origin_key, "well_id": int(well), "fluid": fluid, "period_key": int(period_key(int(panel.period_index[peak + m]))),
             "fitted_volume": float(v)}
            for m, v in zip(months.tolist(), volume.tolist(), strict=True)
        )
    return out


def _point_frame(out: _Collected, panel: SeriesPanel, fluid: str, horizons: np.ndarray, origin: int, target_days: np.ndarray) -> pd.DataFrame:
    n, h = len(out.meta), len(horizons)
    if n == 0:
        return pd.DataFrame(columns=["row", "fluid", "origin", "horizon", "method", "segment", "age_bucket", "fit_status", "target_days", "p50"])
    meta = out.meta
    return pd.DataFrame(
        {
            "row": np.repeat([m[0] for m in meta], h),
            "fluid": fluid,
            "origin": origin,
            "horizon": np.tile(horizons, n),
            "method": np.repeat([m[3] for m in meta], h),
            "segment": np.repeat([m[1] for m in meta], h),
            "age_bucket": np.repeat([m[2] for m in meta], h),
            "fit_status": np.repeat([m[4] for m in meta], h),
            "target_days": np.tile(target_days, n),
            "p50": np.concatenate(out.p50),
        }
    )


def _ml_frame(panel: SeriesPanel, fluid: str, col: int, horizons: np.ndarray, origin: int, cfg, active: dict[int, tuple[str, str]]) -> pd.DataFrame:
    """Quantile models per horizon trained on targets not after the origin, applied to every active series."""
    eps = cfg.backtest.epsilon_rate
    rows = np.array(sorted(active), dtype=np.int64)
    parts = []
    for horizon in horizons.tolist():
        X, y = training_examples(panel, fluid, horizon, col, cfg.ml, eps)
        if len(X) == 0:
            continue
        models = fit_quantile_models(X, y, cfg.ml)
        days = np.full(rows.size, float(days_in_months(np.array([origin + horizon]))[0]))
        volumes = predict_volumes(models, features_at(panel, fluid, col, rows, horizon, eps), base_rate(panel, fluid, col, rows), days, eps)
        parts.append(
            pd.DataFrame(
                {
                    "row": rows, "fluid": fluid, "origin": origin, "horizon": horizon, "method": ML_METHOD,
                    "segment": [active[r][0] for r in rows.tolist()], "age_bucket": [active[r][1] for r in rows.tolist()],
                    "fit_status": "ok", "target_days": days, "p10": volumes[:, 0], "p50": volumes[:, 1], "p90": volumes[:, 2],
                }
            )
        )
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def run_production_forecast(ctx: RunContext) -> dict:
    """The ``forecast`` task: 12-month P10/P50/P90 of every active series at the last published month."""
    cfg = ctx.cfg
    started = time.perf_counter()
    errors = _load_errors(cfg.paths.interim_dir)
    conn = connect(cfg.paths.warehouse)
    try:
        apply_schema(conn)
        selection = read_selection(conn)
        if selection.empty:
            raise ValueError("model_selection is empty: run the backtest task before the forecast (it chooses the method in use)")
        panel = model_panel(conn, cfg)
        col = len(panel.period_index) - 1
        origin = int(panel.period_index[col])
        origin_key = int(period_key(origin))
        horizons = np.arange(1, cfg.backtest.max_horizon + 1, dtype=np.int64)
        target_days = days_in_months(origin + horizons).astype(np.float64)
        t_panel = time.perf_counter()

        frames, fits, curves = [], [], []
        counts = {"eligible": 0, "young": 0}
        seconds = {"fits": 0.0, "ml": 0.0, "bands": 0.0}
        for fluid in FLUIDS:
            mark = time.perf_counter()
            collected = _point_methods(panel, fluid, col, horizons, cfg, origin_key, ctx.run_key)
            fits += collected.fits
            curves += collected.curves
            for segment in counts:
                counts[segment] += collected.counts[segment]
            point = _point_frame(collected, panel, fluid, horizons, origin, target_days)
            seconds["fits"] += time.perf_counter() - mark
            mark = time.perf_counter()
            active = {m[0]: (m[1], m[2]) for m in collected.meta}
            ml = _ml_frame(panel, fluid, col, horizons, origin, cfg, active)
            seconds["ml"] += time.perf_counter() - mark
            mark = time.perf_counter()
            if not point.empty:
                point["p10"], point["p90"] = bands_at_origin(point, errors, origin, cfg.backtest)
            seconds["bands"] += time.perf_counter() - mark
            frames += [f for f in (point, ml) if not f.empty]
        forecast = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["row"])

        operator = panel.categories["operator"]
        codes = panel.period_codes["operator"][:, col]
        company = np.array([operator[c] if c >= 0 else None for c in codes], dtype=object)
        chosen = {(r.fluid, r.segment): r.method for r in selection.itertuples()}
        n_before = len(forecast)
        forecast = forecast[forecast["p10"].notna() & forecast["p90"].notna()].copy()
        without_bands = n_before - len(forecast)
        if without_bands:
            logger.warning("forecast %s: %d rows have no band (no realized error for their method and horizon) and were not written", ctx.run_key, without_bands)
        forecast["origin_period_key"] = origin_key
        forecast["well_id"] = panel.well_ids[forecast["row"].to_numpy()]
        forecast["run_key"] = ctx.run_key
        forecast["target_period_key"] = period_key(origin + forecast["horizon"].to_numpy(dtype=np.int64))
        forecast["company_code"] = company[forecast["row"].to_numpy()]
        forecast["is_selected"] = [int(chosen.get((f, s)) == m) for f, s, m in zip(forecast["fluid"], forecast["segment"], forecast["method"], strict=True)]
        forecast = forecast.sort_values(["fluid", "well_id", "method", "horizon"], kind="stable")

        mark = time.perf_counter()
        fit_frame = pd.DataFrame(fits, columns=FIT_COLUMNS)
        curve_frame = pd.DataFrame(curves, columns=CURVE_COLUMNS)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM model_forecast WHERE origin_period_key = ?", (origin_key,))
            conn.execute("DELETE FROM model_fit WHERE origin_period_key = ?", (origin_key,))
            conn.execute("DELETE FROM model_fitted_curve")  # only the latest origin's curve is kept
            conn.executemany(
                f"INSERT INTO model_forecast ({', '.join(FORECAST_COLUMNS)}) VALUES ({', '.join('?' for _ in FORECAST_COLUMNS)})",
                _rows(forecast, FORECAST_COLUMNS),
            )
            conn.executemany(f"INSERT INTO model_fit ({', '.join(FIT_COLUMNS)}) VALUES ({', '.join('?' for _ in FIT_COLUMNS)})", _rows(fit_frame, FIT_COLUMNS))
            conn.executemany(
                f"INSERT INTO model_fitted_curve ({', '.join(CURVE_COLUMNS)}) VALUES ({', '.join('?' for _ in CURVE_COLUMNS)})",
                _rows(curve_frame, CURVE_COLUMNS),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        done = time.perf_counter()
    finally:
        conn.close()
    result = {
        "origin_period_key": origin_key,
        "wells": int(len(panel.well_ids)),
        "series": counts,
        "forecast_rows": int(len(forecast)),
        "rows_without_bands": int(without_bands),
        "fit_rows": int(len(fit_frame)),
        "curve_rows": int(len(curve_frame)),
        "fallback_rate": {
            variant: float((fit_frame[fit_frame["method"] == variant]["status"] != "ok").mean()) if (fit_frame["method"] == variant).any() else None
            for variant in ARPS_METHODS
        },
        "selected": {f"{f}/{s}": m for (f, s), m in sorted(chosen.items())},
        "seconds": {"panel": t_panel - started, **seconds, "write": done - mark, "total": done - started},
    }
    logger.info(
        "forecast %s: origin %d, %d rows (%d without bands), %d fits, %d curve points, %.1f s",
        ctx.run_key, origin_key, result["forecast_rows"], without_bands, result["fit_rows"], result["curve_rows"], result["seconds"]["total"],
    )
    return result
