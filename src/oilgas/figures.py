"""Figures of the documentation, drawn with matplotlib from the warehouse of a run (plan section 17).

Four PNG files, always from real outputs and never from constants: one well with its fitted curve and
bands, the error of every method by horizon, the coverage of the P10-P90 bands against the target and the
basin with its projection. The files are deterministic (no timestamp in the metadata), so a versioned
figure changes only when its data does. Nothing is written unless every figure was drawn.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from oilgas.files import atomic_path
from oilgas.reporting import read_summary

FIGURE_NAMES = ("example_well_fit.png", "method_comparison.png", "coverage.png", "basin_forecast.png")
DEFAULT_TARGET = 0.8
DEFAULT_ACCEPTABLE = (0.70, 0.90)
DPI = 130
HISTORY_MONTHS = 60
FLUID_ES = {"oil": "Petróleo", "gas": "Gas"}
# Axis unit of the basin chart: the stored volume divided by `scale` (oil in m³, gas in thousand m³); the tables keep their units.
BASIN_UNITS = {"oil": (1e6, "millones de m³ por mes", 1), "gas": (1e3, "millones de m³ por mes", 0)}  # scale, axis label, tick decimals
METHOD_LABELS = {
    "naive_last": "Repetir el último mes",
    "naive_mean3": "Promedio de 3 meses",
    "arps_exp": "Arps exponencial",
    "arps_mh_b2": "Curva de Arps (b hasta 2)",
    "arps_mh_b1": "Curva de Arps (b hasta 1)",
    "ml_hgb": "Machine learning",
}
METHOD_COLORS = {
    "naive_last": "#8a8f98", "naive_mean3": "#eda100", "arps_exp": "#1baf7a",
    "arps_mh_b2": "#2a78d6", "arps_mh_b1": "#6250d6", "ml_hgb": "#eb6834",
}
COVERAGE_METHODS = ("naive_last", "naive_mean3", "arps_mh_b2", "ml_hgb")
INK, GRID, MUTED = "#1f2430", "#e4e6ea", "#5b6270"


# --- data -------------------------------------------------------------------------------------------------------


def coverage_target(reports_dir: Path) -> float:
    """The preregistered coverage target of the run's summary, or the default when there is no summary yet."""
    return _thresholds(reports_dir).get("coverage_target", DEFAULT_TARGET)


def _thresholds(reports_dir: Path) -> dict:
    path = Path(reports_dir) / "backtest_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("criteria", {}).get("thresholds", {})


def _month(period_key: int) -> pd.Timestamp:
    return pd.Timestamp(year=int(period_key) // 100, month=int(period_key) % 100, day=1)


def _months(keys) -> list[pd.Timestamp]:
    return [_month(k) for k in keys]


def example_well(conn: sqlite3.Connection) -> int | None:
    """The largest producer among the wells with a correct base Arps fit at the latest origin (the dashboard's choice)."""
    row = conn.execute(
        "SELECT f.well_id FROM model_fit f JOIN dim_well w ON w.well_key = f.well_id "
        "WHERE f.fluid = 'oil' AND f.method = 'arps_mh_b2' AND f.status = 'ok' "
        "AND f.origin_period_key = (SELECT MAX(origin_period_key) FROM model_fit) "
        "ORDER BY w.cum_oil_m3 DESC, f.well_id LIMIT 1").fetchone()
    return None if row is None else int(row[0])


def basin_series(conn: sqlite3.Connection, fluid: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The basin's produced volume by month and its projection: the sum, over wells, of the method in use (P10, P50, P90)."""
    column = {"oil": "oil_m3", "gas": "gas_thousand_m3"}[fluid]
    produced = pd.read_sql_query(f"SELECT period_key, SUM({column}) AS volume FROM fact_production_monthly GROUP BY period_key ORDER BY period_key", conn)
    projected = pd.read_sql_query(
        "SELECT target_period_key AS period_key, SUM(p10) AS p10, SUM(p50) AS p50, SUM(p90) AS p90 FROM model_forecast "
        "WHERE fluid = ? AND is_selected = 1 AND origin_period_key = (SELECT MAX(origin_period_key) FROM model_forecast) "
        "GROUP BY target_period_key ORDER BY target_period_key", conn, params=(fluid,))
    return produced, projected


def _query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


# --- drawing helpers --------------------------------------------------------------------------------------------


def _spanish(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _style(ax, y_label: str | None = None) -> None:
    ax.set_facecolor("white")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    if y_label:
        ax.set_ylabel(y_label, color=MUTED, fontsize=9)


def _figure(width: float, height: float) -> Figure:
    fig = Figure(figsize=(width, height), dpi=DPI, facecolor="white")
    FigureCanvasAgg(fig)
    return fig


def _title(fig: Figure, title: str, subtitle: str) -> None:
    fig.text(0.01, 0.975, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.01, 0.925, subtitle, fontsize=9, color=MUTED, va="top")


# --- the four figures -------------------------------------------------------------------------------------------


def _draw_well(conn: sqlite3.Connection) -> Figure:
    well = example_well(conn)
    fig = _figure(10, 5.4)
    subtitle = "Sin pozos con un ajuste correcto" if well is None else (
        f"Pozo {well}, el de mayor producción acumulada con un ajuste correcto. La línea punteada vertical marca el último mes publicado.")
    _title(fig, "Un pozo, su curva y sus bandas", subtitle)
    ax = fig.add_axes([0.08, 0.13, 0.9, 0.7])
    _style(ax, "Petróleo (m³ por mes)")
    if well is None:
        ax.text(0.5, 0.5, "Sin pozos con un ajuste de Arps correcto", ha="center", transform=ax.transAxes, color=MUTED)
        return fig
    history = _query(conn, "SELECT period_key, oil_m3 FROM fact_production_monthly WHERE well_key = ? ORDER BY period_key", (well,)).tail(HISTORY_MONTHS)
    origin = int(history["period_key"].max())
    curve = _query(conn, "SELECT period_key, fitted_volume FROM model_fitted_curve WHERE well_id = ? AND fluid = 'oil' "
                         "AND origin_period_key = (SELECT MAX(origin_period_key) FROM model_fitted_curve) ORDER BY period_key", (well,))
    curve = curve[curve["period_key"] >= history["period_key"].min()]
    forecast = _query(conn, "SELECT method, target_period_key AS period_key, p10, p50, p90 FROM model_forecast WHERE well_id = ? AND fluid = 'oil' "
                            "AND origin_period_key = ? AND method IN ('arps_mh_b2', 'ml_hgb') ORDER BY method, horizon", (well, origin))
    ax.plot(_months(history["period_key"]), history["oil_m3"], color=INK, linewidth=1.8, label="Producido")
    ax.plot(_months(curve["period_key"]), curve["fitted_volume"], color=METHOD_COLORS["arps_mh_b2"], linewidth=1.3, linestyle=":", label="Curva ajustada")
    for method in ("arps_mh_b2", "ml_hgb"):
        part = forecast[forecast["method"] == method]
        if part.empty:
            continue
        months = _months(part["period_key"])
        ax.fill_between(months, part["p10"], part["p90"], color=METHOD_COLORS[method], alpha=0.16, linewidth=0)
        ax.plot(months, part["p50"], color=METHOD_COLORS[method], linewidth=2, label=f"{METHOD_LABELS[method]}: P50 y banda P10-P90")
    ax.axvline(_month(origin), color=MUTED, linewidth=0.8, linestyle="--")
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _spanish(v)))
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    return fig


def _draw_methods(summary: pd.DataFrame) -> Figure:
    fig = _figure(10, 4.8)
    _title(fig, "Error de cada método según el horizonte", "WAPE sobre las series elegibles: suma de los errores absolutos dividida por la suma de lo producido. Menos es mejor.")
    rows = summary[summary["segment"] == "eligible"]
    methods = [m for m in METHOD_LABELS if m in set(rows["method"])]
    axes = fig.subplots(1, 2, sharey=False, gridspec_kw={"left": 0.07, "right": 0.99, "top": 0.78, "bottom": 0.14, "wspace": 0.22})
    for ax, fluid in zip(axes, ("oil", "gas"), strict=True):
        _style(ax, "WAPE (%)" if fluid == "oil" else None)
        part = rows[rows["fluid"] == fluid]
        horizons = sorted({int(h) for h in part["horizon"]})
        width = 0.8 / max(len(methods), 1)
        for i, method in enumerate(methods):
            values = [part[(part["method"] == method) & (part["horizon"] == h)]["wape"] for h in horizons]
            heights = [float(v.iloc[0]) * 100 if len(v) and pd.notna(v.iloc[0]) else np.nan for v in values]
            ax.bar(np.arange(len(horizons)) + (i - (len(methods) - 1) / 2) * width, heights, width * 0.92, color=METHOD_COLORS[method], label=METHOD_LABELS[method])
        ax.set_xticks(np.arange(len(horizons)), [f"{h} {'mes' if h == 1 else 'meses'}" for h in horizons])
        ax.set_title(FLUID_ES[fluid], loc="left", fontsize=11, color=INK)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _spanish(v)))
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    return fig


def _draw_coverage(summary: pd.DataFrame, target: float, acceptable: tuple[float, float]) -> Figure:
    fig = _figure(10, 4.8)
    _title(fig, "Cobertura de las bandas P10-P90", f"Proporción de los valores reales dentro de la banda. Objetivo {_spanish(target, 2)}; zona sombreada: aceptable ({_spanish(acceptable[0], 2)} a {_spanish(acceptable[1], 2)}).")
    rows = summary[summary["segment"] == "eligible"]
    lowest = float(rows[rows["method"].isin(COVERAGE_METHODS)]["coverage"].min())
    axes = fig.subplots(1, 2, sharey=True, gridspec_kw={"left": 0.07, "right": 0.99, "top": 0.78, "bottom": 0.14, "wspace": 0.08})
    for ax, fluid in zip(axes, ("oil", "gas"), strict=True):
        _style(ax, "Cobertura" if fluid == "oil" else None)
        ax.axhspan(acceptable[0], acceptable[1], color="#1baf7a", alpha=0.10, linewidth=0)
        ax.axhline(target, color=INK, linewidth=1, linestyle="--")
        part = rows[rows["fluid"] == fluid]
        horizons = sorted({int(h) for h in part["horizon"]})
        for method in COVERAGE_METHODS:
            sub = part[part["method"] == method].set_index("horizon")["coverage"]
            if sub.empty:
                continue
            ax.plot(horizons, [sub.get(h, np.nan) for h in horizons], marker="o", color=METHOD_COLORS[method], linewidth=2, label=METHOD_LABELS[method])
        ax.set_xticks(horizons, [str(h) for h in horizons])
        ax.set_xlabel("Horizonte (meses)", color=MUTED, fontsize=9)
        ax.set_title(FLUID_ES[fluid], loc="left", fontsize=11, color=INK)
        ax.set_ylim(min(0.6, np.floor((lowest - 0.05) * 20) / 20), 1.0)  # show the acceptable zone; widen only if a method falls below it
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _spanish(v, 2)))
    axes[1].legend(frameon=False, fontsize=8, loc="lower left", ncols=2)
    return fig


def _draw_basin(conn: sqlite3.Connection) -> Figure:
    fig = _figure(10, 4.8)
    _title(fig, "La cuenca: lo producido y lo proyectado",
           "Proyección con el método en uso de cada pozo activo hoy; no incluye pozos nuevos. La banda suma el P10 y el P90 de cada pozo: es más ancha que la incertidumbre real del total.")
    axes = fig.subplots(1, 2, gridspec_kw={"left": 0.08, "right": 0.99, "top": 0.78, "bottom": 0.14, "wspace": 0.28})
    for ax, fluid in zip(axes, ("oil", "gas"), strict=True):
        scale, unit, digits = BASIN_UNITS[fluid]
        _style(ax, unit)
        produced, projected = basin_series(conn, fluid)
        produced = produced.tail(HISTORY_MONTHS)
        ax.plot(_months(produced["period_key"]), produced["volume"] / scale, color=INK, linewidth=1.8, label="Producido")
        if not projected.empty:
            months = _months(projected["period_key"])
            ax.fill_between(months, projected["p10"] / scale, projected["p90"] / scale, color=METHOD_COLORS["arps_mh_b2"], alpha=0.16, linewidth=0, label="Suma de P10 a P90 por pozo")
            ax.plot(months, projected["p50"] / scale, color=METHOD_COLORS["arps_mh_b2"], linewidth=2, label="Proyectado (P50)")
        ax.set_title(FLUID_ES[fluid], loc="left", fontsize=11, color=INK)
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _, d=digits: _spanish(v, d)))
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    return fig


# --- entry point ------------------------------------------------------------------------------------------------


def make_figures(conn: sqlite3.Connection, reports_dir: Path, out_dir: Path) -> list[Path]:
    """Draw the four figures from the warehouse and write them to `out_dir`; returns the paths in a fixed order.

    Nothing is written if the warehouse has no backtest summary or a figure fails to draw.
    """
    summary = read_summary(conn)
    if summary.empty:
        raise ValueError("the warehouse has no backtest summary: run the pipeline first (python -m oilgas run)")
    thresholds = _thresholds(reports_dir)
    acceptable = tuple(thresholds.get("coverage_acceptable", DEFAULT_ACCEPTABLE))
    drawn = {
        "example_well_fit.png": _draw_well(conn),
        "method_comparison.png": _draw_methods(summary),
        "coverage.png": _draw_coverage(summary, thresholds.get("coverage_target", DEFAULT_TARGET), acceptable),
        "basin_forecast.png": _draw_basin(conn),
    }
    out_dir = Path(out_dir)
    paths = []
    for name in FIGURE_NAMES:
        path = out_dir / name
        with atomic_path(path) as temporary:
            drawn[name].savefig(temporary, format="png", metadata={"Software": None})
        paths.append(path)
    return paths
