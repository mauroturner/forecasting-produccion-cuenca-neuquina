"""The HTML design of the Power BI report, generated from the semantic model and the exported Parquet (RF18, D14).

One self-contained page (inline CSS, inline SVG, no scripts, no fonts or images from the network) with the
steps to build the report in Power BI Desktop, the diagram of the model, the 25 relationships, the Power
Query code of each table, the DAX measures and the five pages placed on a 12 x 9 grid, each visual with a
preview drawn from the real tables. Nothing here is typed by hand twice: change ``semantic_model.py`` and
render again.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from oilgas.dashboard import svg
from oilgas.dashboard.semantic_model import (
    PAGE_COLUMNS,
    PAGE_HEIGHT_PX,
    PAGE_ROWS,
    PAGE_WIDTH_PX,
    Page,
    SemanticModel,
    Visual,
    dax_measure_refs,
    validate_model,
)
from oilgas.files import write_atomic

logger = logging.getLogger(__name__)

CELL_W, CELL_H = PAGE_WIDTH_PX / PAGE_COLUMNS, PAGE_HEIGHT_PX / PAGE_ROWS
HEADER_PX = 26  # height of a visual's title row
PREVIEW_MONTHS = 60
TITLE = "Diseño del tablero de Power BI: producción de petróleo y gas, pozo por pozo"
SECTIONS = (
    ("armado", "Cómo armarlo en Power BI Desktop"),
    ("modelo", "El modelo en estrella"),
    ("relaciones", "Relaciones"),
    ("consultas", "Power Query: una consulta por tabla"),
    ("medidas", "Medidas DAX"),
    ("paginas", "Las cinco páginas"),
    ("fuente", "Fuente y licencia"),
)
KIND_ES = {
    "slicer": "Segmentador", "card": "Tarjeta", "multiRowCard": "Tarjeta de varias filas", "lineChart": "Gráfico de líneas",
    "barChart": "Gráfico de barras", "clusteredColumnChart": "Columnas agrupadas", "scatterChart": "Dispersión",
    "matrix": "Matriz", "treemap": "Mapa de árbol", "table": "Tabla", "text": "Cuadro de texto",
}
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--panel:#f3f2ef;--text:#0b0b0b;--text-2:#52514e;--muted:#6f6e69;--line:#d9d8d3;--accent:#256abf;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--series-5:#e87ba4;--series-6:#008300;--series-7:#6250d6;--series-8:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 4px}h2{font-size:1.3rem;margin:48px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:28px 0 8px}p,li{max-width:78ch}a{color:var(--accent)}
.lead{color:var(--text-2);margin:0 0 16px}.meta{display:flex;flex-wrap:wrap;gap:8px 24px;color:var(--text-2);font-size:.9rem;margin:12px 0}
nav ul{display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;list-style:none;margin:16px 0}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.85rem}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;margin:6px 0;white-space:pre}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--text-2);font-weight:600;position:sticky;top:0;background:var(--surface)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}.warn{border-left:3px solid var(--series-4);padding:4px 12px;background:var(--panel);margin:12px 0}
.model-svg{width:100%;height:auto;display:block}.model-svg .box{fill:var(--panel);stroke:var(--line)}.model-svg .dim{stroke:var(--series-1)}
.model-svg .fact{stroke:var(--series-2)}.model-svg text{fill:var(--text);font-size:12px}.model-svg .small{fill:var(--text-2);font-size:10px}
.model-svg .rel{stroke:var(--muted);stroke-width:1;fill:none;opacity:.55}.model-svg .card{font-weight:700;fill:var(--accent)}
.canvas-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px}
.canvas{display:grid;grid-template-columns:repeat(12,1fr);grid-template-rows:repeat(9,1fr);gap:6px;aspect-ratio:16/9;min-width:960px;max-width:1280px}
.visual{background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}
.visual header{display:flex;justify-content:space-between;gap:6px;padding:2px 8px;font-size:.75rem;color:var(--text-2);height:26px;align-items:center}
.visual header b{color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.visual header span{white-space:nowrap;color:var(--muted)}
.visual .body{flex:1;min-height:0;padding:0 8px 3px;overflow:hidden;font-size:.75rem}.visual .body svg{max-width:100%;height:auto;display:block}
.big{font-size:1.2rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{color:var(--muted);font-size:.65rem;line-height:1.1}
.chips{display:flex;flex-wrap:nowrap;gap:3px;overflow:hidden}.chip{white-space:nowrap;border:1px solid var(--line);border-radius:10px;padding:0 6px;font-size:.7rem;color:var(--text-2)}
.visual table{font-size:.7rem}.visual th,.visual td{padding:1px 5px}.rows p{margin:1px 0;font-size:.75rem}
svg .svg-grid{stroke:var(--line);stroke-width:1}svg .svg-axis{stroke:var(--muted);stroke-width:1}svg .svg-reference{stroke:var(--text-2);stroke-width:1;stroke-dasharray:2 3}
svg .svg-tick,svg .svg-legend,svg .svg-note,svg .svg-value{fill:var(--text-2);font-size:10px}svg .svg-value{fill:var(--text)}svg .svg-on-fill{fill:var(--text);font-size:10px}
svg .svg-band{fill:var(--series-1);fill-opacity:.15}svg .svg-hit{fill:transparent}svg .svg-hit:hover{fill:var(--text);fill-opacity:.15}
.placement td:first-child{white-space:nowrap}
@media print{.canvas-wrap{break-inside:avoid}body{font-size:12px}}
"""


# --- data ---------------------------------------------------------------------------------------------------------


class _Data:
    """The exported tables and the figures the previews are drawn from."""

    def __init__(self, outputs_dir: Path, model: SemanticModel) -> None:
        self.dir = Path(outputs_dir)
        self.t: dict[str, pd.DataFrame] = {}
        for table in model.tables:
            path = self.dir / f"{table.name}.parquet"
            self.t[table.name] = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=list(table.column_names))
        first = next((self.dir / f"{t.name}.parquet" for t in model.tables if (self.dir / f"{t.name}.parquet").exists()), None)
        meta = {k.decode(): v.decode() for k, v in (pq.read_schema(first).metadata or {}).items()} if first else {}
        self.run_key = meta.get("oilgas.run_key", "—")
        self.sha = meta.get("oilgas.source_sha256", "—")
        cal = self.t["dim_calendar"]
        self.index_of = dict(zip(cal["period_key"], cal["period_index"], strict=True))
        published = cal[cal["is_published"].astype(bool)]
        self.last_key = int(published["period_key"].max()) if len(published) else 0
        self.last_index = self.index_of.get(self.last_key, 0)
        forecast, origin = self.t["fact_forecast"], self.t["dim_origin"]
        self.origin = int(origin["origin_period_key"].max()) if len(origin) else 0
        selected = forecast[forecast["is_selected"].astype(bool) & (forecast["origin_period_key"] == self.origin)]
        self.selected = selected
        prod = self.t["fact_production_monthly"]
        self.prod = prod
        self.monthly = prod.groupby("period_key").agg(oil=("oil_m3", "sum"), gas=("gas_thousand_m3", "sum"), rows=("well_key", "size"))
        self.wells_total = len(self.t["dim_well"])
        self.wells_forecast = forecast["well_key"].nunique() if len(forecast) else 0

    def index(self, period_key: int) -> int:
        return int(self.index_of.get(int(period_key), 0))

    def label(self, period_key: int) -> str:
        return f"{int(period_key) // 100}-{int(period_key) % 100:02d}"

    def window(self, months: int = PREVIEW_MONTHS) -> list[int]:
        """The last `months` published period keys that have production."""
        keys = [k for k in self.monthly.index if self.index(k) <= self.last_index]
        return sorted(keys)[-months:]

    def x_ticks(self, keys: list[int]) -> list[tuple[float, str]]:
        """A tick at each January in `keys` (labelled with the year), plus the first month."""
        ticks = [(self.index(k), str(k // 100)) for k in keys if k % 100 == 1]
        return ticks or ([(self.index(keys[0]), self.label(keys[0]))] if keys else [])

    def fluid_column(self, fluid: str) -> str:
        return "oil" if fluid == "oil" else "gas"

    def forecast_sum(self, fluid: str) -> pd.DataFrame:
        rows = self.selected[self.selected["fluid_key"] == fluid]
        return rows.groupby("target_period_key")[["p10", "p50", "p90"]].sum()

    def last_twelve(self) -> list[int]:
        return self.window(12)


def _fmt(value, digits: int = 1) -> str:
    """A number in Spanish with at least one decimal where it is abbreviated (4,8 M, not 5 M)."""
    return svg.format_number(value, max(digits, 1))


def _table_html(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    head = "".join(f'<th{" class=num" if i in numeric else ""}>{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td{" class=num" if i in numeric else ""}>{escape(str(c))}</td>' for i, c in enumerate(row)) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body or '<tr><td>Sin datos</td></tr>'}</tbody></table>"


def _size(v: Visual) -> tuple[int, int]:
    """Pixels available for a visual's drawing (the canvas is 1280 x 720)."""
    return max(int(v.w * CELL_W - 22), 60), max(int(v.h * CELL_H - HEADER_PX - 12), 40)


# --- previews -------------------------------------------------------------------------------------------------------


def _slicer(data: _Data, field: str) -> str:
    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
    values = data.t[table][column].dropna() if column in data.t[table] else pd.Series(dtype=object)
    if column == "month_start":
        values = values.astype(str)
    shown = [str(v) for v in values.value_counts().index[:4]] if len(values) else []
    chips = "".join(f'<span class="chip">{escape(v)}</span>' for v in shown)
    more = f'<span class="chip">+{values.nunique() - len(shown)}</span>' if values.nunique() > len(shown) else ""
    return f'<div class="chips">{chips or "Sin datos"}{more}</div>'


def _card(big: str, sub: str = "") -> str:
    return f'<div class="big">{escape(big)}</div><div class="sub">{escape(sub)}</div>'


def _production_line(data: _Data, fluid: str, v: Visual) -> str:
    w, h = _size(v)
    keys = data.window()
    column = data.fluid_column(fluid)
    history = [(data.index(k), float(data.monthly.loc[k, column])) for k in keys]
    forecast = data.forecast_sum(fluid)
    p50 = [(data.index(k), float(r.p50)) for k, r in forecast.iterrows()]
    band = [(data.index(k), float(r.p10), float(r.p90)) for k, r in forecast.iterrows()]
    unit = "m³" if fluid == "oil" else "miles de m³"
    series = {"Producido": history, "P50 (método en uso)": p50}
    ticks = data.x_ticks(keys + list(forecast.index))
    return svg.line_chart(series, w, h, v.title_es, dashed=("P50 (método en uso)",), band=band or None, band_label="Suma de P10-P90 por pozo", x_ticks=ticks, unit=unit)


def _last_twelve_by(data: _Data, key: str) -> pd.Series:
    keys = data.last_twelve()
    return data.prod[data.prod["period_key"].isin(keys)].groupby(key)["oil_m3"].sum()


def _top_companies(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    totals = _last_twelve_by(data, "company_key").sort_values(ascending=False).head(10)
    names = data.t["dim_company"].set_index("company_key")["company_name"]
    return svg.bar_chart([(str(names.get(k, k)), float(t)) for k, t in totals.items()], w, h, v.title_es, unit="m³")


def _wells_scatter(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    wells = data.t["dim_well"].dropna(subset=["lon", "lat"])
    return svg.scatter_chart(
        [(float(r.lon), float(r.lat), str(r.sub_resource_type) if pd.notna(r.sub_resource_type) else "Sin dato") for r in wells.itertuples()],
        w, h, v.title_es,
    )


def _p10_p90_table(data: _Data) -> str:
    forecast = data.forecast_sum("oil")
    rows = [[data.label(k), _fmt(r.p10, 0), _fmt(r.p90, 0)] for k, r in forecast.head(4).iterrows()]
    return _table_html(["Mes", "Σ P10", "Σ P90"], rows, {1, 2})


def _company_matrix(data: _Data) -> str:
    prod = data.prod.assign(year=data.prod["period_key"] // 100)
    years = sorted(prod["year"].unique())[-5:]
    totals = prod[prod["year"].isin(years)].groupby(["company_key", "year"])["oil_m3"].sum().unstack(fill_value=0.0)
    names = data.t["dim_company"].set_index("company_key")["company_name"]
    top = totals.sum(axis=1).sort_values(ascending=False).head(6).index
    rows = [[str(names.get(c, c)), *[_fmt(totals.loc[c].get(y, 0.0), 0) for y in years]] for c in top]
    return _table_html(["Empresa (petróleo, m³)", *[str(int(y)) for y in years]], rows, set(range(1, len(years) + 1)))


def _field_table(data: _Data) -> tuple[pd.DataFrame, pd.DataFrame]:
    wells = data.t["dim_well"].set_index("well_key")["field_name"]
    keys, previous = data.last_twelve(), data.window(24)[:12]
    last = data.prod[data.prod["period_key"].isin(keys)].assign(field=lambda f: f["well_key"].map(wells))
    before = data.prod[data.prod["period_key"].isin(previous)].assign(field=lambda f: f["well_key"].map(wells))
    producing = data.prod[(data.prod["period_key"] == data.last_key) & data.prod["is_producing"].astype(bool)].assign(field=lambda f: f["well_key"].map(wells))
    forecast = data.selected[data.selected["fluid_key"] == "oil"].assign(field=lambda f: f["well_key"].map(wells))
    table = pd.DataFrame(
        {
            "wells": producing.groupby("field")["well_key"].nunique(),
            "oil12": last.groupby("field")["oil_m3"].sum(),
            "oil_prev": before.groupby("field")["oil_m3"].sum(),
            "p50": forecast.groupby("field")["p50"].sum(),
        }
    ).fillna(0.0)
    return table.sort_values("oil12", ascending=False), last


def _field_treemap(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    table, _ = _field_table(data)
    return svg.treemap([(str(k), float(r.oil12)) for k, r in table.head(14).iterrows()], w, h, v.title_es)


def _field_rows(data: _Data) -> str:
    table, _ = _field_table(data)
    rows = []
    for field, r in table.head(8).iterrows():
        change = "—" if r.oil_prev <= 0 else f"{(r.oil12 - r.oil_prev) / r.oil_prev * 100:+.0f} %".replace(".", ",")
        rows.append([str(field), _fmt(r.wells, 0), _fmt(r.oil12, 0), _fmt(r.p50, 0), change])
    return _table_html(["Yacimiento", "Pozos", "Petróleo 12 m", "P50 próx. 12 m", "Var."], rows, {1, 2, 3, 4})


def _example_well(data: _Data) -> int | None:
    """The well the Pozo page is drawn for: the largest producer among those with a base Arps fit."""
    fits = data.t["fact_well_fit"]
    ok = fits[(fits["fluid_key"] == "oil") & (fits["method_key"] == "arps_mh_b2") & (fits["status"] == "ok") & (fits["origin_period_key"] == data.origin)]
    wells = data.t["dim_well"].set_index("well_key")
    candidates = wells.loc[wells.index.intersection(ok["well_key"])]
    pool = candidates if len(candidates) else wells
    return int(pool["cum_oil_m3"].idxmax()) if len(pool) else None


def _well_line(data: _Data, v: Visual, well: int | None) -> str:
    w, h = _size(v)
    if well is None:
        return svg.line_chart({}, w, h, v.title_es)
    keys = data.window(48)
    prod = data.prod[data.prod["well_key"] == well].set_index("period_key")["oil_m3"]
    series: dict[str, list[tuple[float, float]]] = {"Producido": [(data.index(k), float(prod.get(k, float("nan")))) for k in keys]}
    curve = data.t["fact_fitted_curve"]
    curve = curve[(curve["well_key"] == well) & (curve["fluid_key"] == "oil")]
    series["Curva ajustada"] = [(data.index(k), float(x)) for k, x in zip(curve["period_key"], curve["fitted_volume"], strict=True) if k in keys]
    forecast = data.t["fact_forecast"]
    forecast = forecast[(forecast["well_key"] == well) & (forecast["fluid_key"] == "oil") & (forecast["origin_period_key"] == data.origin)]
    names = data.t["dim_method"].set_index("method_key")["method_name_es"]
    dashed = []
    for method, rows in forecast.groupby("method_key"):
        label = str(names.get(method, method))
        series[f"P50 {label}"] = [(data.index(k), float(x)) for k, x in zip(rows["target_period_key"], rows["p50"], strict=True)]
        dashed.append(f"P50 {label}")
    return svg.line_chart(series, w, h, v.title_es, dashed=tuple(dashed), x_ticks=data.x_ticks(keys), unit="m³")


def _fit_card(data: _Data, well: int | None) -> str:
    fits = data.t["fact_well_fit"]
    fit = fits[(fits["well_key"] == well) & (fits["fluid_key"] == "oil") & (fits["method_key"] == "arps_mh_b2") & (fits["origin_period_key"] == data.origin)]
    if fit.empty:
        return '<div class="rows"><p>Sin ajuste para este pozo.</p></div>'
    r = fit.iloc[0]
    rows = [
        ("qi", f"{_fmt(r.qi_rate_per_day)} m³/día" if pd.notna(r.qi_rate_per_day) else "—"),
        ("Di", f"{_fmt(r.di_nominal_per_month, 3)} por mes" if pd.notna(r.di_nominal_per_month) else "—"),
        ("b", _fmt(r.b, 2) if pd.notna(r.b) else "—"),
        ("Declinación efectiva anual inicial", f"{r.d_effective_annual_initial * 100:.0f} %".replace(".", ",") if pd.notna(r.d_effective_annual_initial) else "—"),
        ("Estado del ajuste", str(r.status)),
    ]
    return '<div class="rows">' + "".join(f"<p><b>{escape(k)}</b>: {escape(val)}</p>" for k, val in rows) + "</div>"


def _well_table(data: _Data, well: int | None) -> str:
    prod = data.prod[data.prod["well_key"] == well].set_index("period_key")
    forecast = data.t["fact_forecast"]
    forecast = forecast[(forecast["well_key"] == well) & (forecast["origin_period_key"] == data.origin) & forecast["is_selected"].astype(bool)]
    p50 = {(r.fluid_key, r.target_period_key): r.p50 for r in forecast.itertuples()}
    rows = [[data.label(k), _fmt(prod.loc[k, "oil_m3"], 0) if k in prod.index else "—", "—", _fmt(prod.loc[k, "gas_thousand_m3"], 0) if k in prod.index else "—", "—"] for k in data.window(3)]
    for key in sorted({k for _, k in p50})[:3]:
        rows.append([data.label(key), "—", _fmt(p50.get(("oil", key), float("nan")), 0), "—", _fmt(p50.get(("gas", key), float("nan")), 0)])
    return _table_html(["Mes", "Petróleo", "P50 pet.", "Gas", "P50 gas"], rows, {1, 2, 3, 4})


def _summary_rows(data: _Data, fluid: str = "oil", segment: str = "eligible") -> pd.DataFrame:
    s = data.t["fact_model_summary"]
    return s[(s["fluid_key"] == fluid) & (s["segment"] == segment)]


def _wape_bars(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    s = _summary_rows(data)
    groups = [(f"{int(hz)} m", {str(r.method_key): float(r.wape) for r in rows.itertuples()}) for hz, rows in s.groupby("horizon")]
    return svg.grouped_bar_chart(groups, w, h, v.title_es, percent=True)


def _coverage_lines(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    s = _summary_rows(data)
    series = {str(m): [(float(r.horizon), float(r.coverage)) for r in rows.itertuples()] for m, rows in s.groupby("method_key")}
    return svg.line_chart(series, w, h, v.title_es, x_ticks=[(float(x), f"{int(x)} m") for x in sorted(s["horizon"].unique())], reference=("Objetivo 0,8", 0.8))


def _beats_bars(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    s = _summary_rows(data)
    if s.empty:
        return svg.bar_chart([], w, h, v.title_es)
    s = s[s["horizon"] == s["horizon"].max()]
    return svg.bar_chart([(str(r.method_key), float(r.share_beats_naive_last) * 100) for r in s.itertuples() if pd.notna(r.share_beats_naive_last)], w, h, v.title_es, unit="%")


def _age_matrix(data: _Data) -> str:
    m = data.t["fact_backtest_metrics"]
    m = m[m["fluid_key"] == "oil"].groupby(["method_key", "age_bucket"])[["sum_abs_error", "sum_actual"]].sum()
    if m.empty:
        return _table_html(["Método"], [])
    wape = (m["sum_abs_error"] / m["sum_actual"]).unstack()
    order = [b for b in ("young", "06-11", "12-23", "24-59", "60+") if b in wape.columns]
    rows = [[str(k), *[("—" if pd.isna(wape.loc[k, b]) else f"{wape.loc[k, b] * 100:.0f} %") for b in order]] for k in wape.index]
    return _table_html(["WAPE (petróleo)", *order], rows, set(range(1, len(order) + 1)))


def _verdict(data: _Data) -> str:
    s = _summary_rows(data)
    s = s[s["method_key"] == "arps_mh_b2"]
    if s.empty:
        return '<div class="sub">Sin veredicto</div>'
    return f'<div class="rows"><p>{escape(str(s.sort_values("horizon").iloc[-1]["verdict_es"]))}</p></div>'


def _wape_by_origin(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    m = data.t["fact_backtest_metrics"]
    m = m[m["fluid_key"] == "oil"].groupby(["method_key", "origin_period_key"])[["sum_abs_error", "sum_actual"]].sum()
    series: dict[str, list[tuple[float, float]]] = {}
    for method in m.index.get_level_values(0).unique():
        part = m.loc[method]
        series[str(method)] = [(float(data.index(k)), float(r.sum_abs_error / r.sum_actual)) for k, r in part.iterrows() if r.sum_actual > 0]
    keys = sorted(m.index.get_level_values(1).unique())
    return svg.line_chart(series, w, h, v.title_es, x_ticks=[(float(data.index(k)), data.label(k)) for k in keys[:: max(1, len(keys) // 6)]])


def _latest_run(data: _Data) -> pd.Series | None:
    runs = data.t["dim_pipeline_run"]
    return runs.sort_values("started_at").iloc[-1] if len(runs) else None


def _days_since(data: _Data) -> str:
    run = _latest_run(data)
    if run is None or not data.last_key or not run["started_at"]:
        return "—"
    year, month = data.last_key // 100, data.last_key % 100
    end = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    when = datetime.fromisoformat(str(run["started_at"])).date()
    return str((when - end).days)


def _blocking_failed(data: _Data) -> str:
    v = data.t["fact_validation"]
    return str(int(((v["severity"] == "bloqueante") & (v["status"] == "falla")).sum()))


def _rules_table(data: _Data) -> str:
    v = data.t["fact_validation"]
    if v.empty:
        return _table_html(["Regla"], [])
    latest = v[v["run_key"] == v["run_key"].iloc[-1]]
    rows = [[r.rule_id, r.name_es, r.severity, str(r.rows_affected), r.status] for r in latest.head(23).itertuples()]
    return _table_html(["ID", "Regla", "Severidad", "Filas", "Estado"], rows, {3})


def _rows_line(data: _Data, v: Visual) -> str:
    w, h = _size(v)
    keys = data.window()
    return svg.line_chart({"Filas por mes": [(data.index(k), float(data.monthly.loc[k, "rows"])) for k in keys]}, w, h, v.title_es, x_ticks=data.x_ticks(keys))


def _runs_table(data: _Data) -> str:
    runs = data.t["dim_pipeline_run"]
    rows = [[r.run_key, str(r.started_at), str(r.status), str(r.last_period_key), str(r.revised_rows)] for r in runs.tail(4).itertuples()]
    return _table_html(["Corrida", "Inicio", "Estado", "Último mes", "Filas revisadas"], rows, {3, 4})


def _yoy(data: _Data) -> str:
    oil = data.monthly["oil"] if len(data.monthly) else pd.Series(dtype=float)
    last, before = oil.get(data.last_key), oil.get(_shift(data.last_key, -12))
    if last is None or not before:
        return "—"
    return f"{(last - before) / before * 100:+.1f} %".replace(".", ",")


def _shift(period_key: int, months: int) -> int:
    index = period_key // 100 * 12 + period_key % 100 - 1 + months
    return index // 12 * 100 + index % 12 + 1


def _preview(data: _Data, page: Page, v: Visual, well: int | None, attribution: str) -> str:
    """The body of a visual: its drawing or figure from the real tables."""
    title = v.title_es
    last = data.last_key
    oil_last = float(data.monthly["oil"].get(last, float("nan"))) if len(data.monthly) else float("nan")
    gas_last = float(data.monthly["gas"].get(last, float("nan"))) if len(data.monthly) else float("nan")
    if v.kind == "slicer":
        return _slicer(data, v.fields[0])
    if v.kind == "text":
        return f'<div class="sub">{escape(attribution)} Datos hasta {escape(data.label(last))}; corrida {escape(data.run_key)}.</div>'
    figures = {
        "Petróleo del último mes (m³)": lambda: _card(_fmt(oil_last, 2), data.label(last)),
        "Gas del último mes (miles de m³)": lambda: _card(_fmt(gas_last, 2), data.label(last)),
        "Variación interanual del petróleo": lambda: _card(_yoy(data), f"{data.label(last)} frente a {data.label(_shift(last, -12))}"),
        "Pozos en producción": lambda: _card(_fmt(float(data.prod[(data.prod["period_key"] == last) & data.prod["is_producing"].astype(bool)]["well_key"].nunique()), 0), data.label(last)),
        "Último mes publicado": lambda: _card(data.label(last), "de la última corrida exitosa"),
        "Provincia": lambda: _card(_well_attr(data, well, "province")),
        "Formación": lambda: _card(_well_attr(data, well, "formation_name")),
        "Subtipo": lambda: _card(_well_attr(data, well, "sub_resource_type")),
        "Operadora": lambda: _card(_well_attr(data, well, "operator_current_name")),
        "Veredicto": lambda: _verdict(data),
        "Días desde el fin de ese mes": lambda: _card(_days_since(data), "a la fecha de la última corrida"),
        "Estado de la última corrida": lambda: _card(str(_latest_run(data)["status"]) if _latest_run(data) is not None else "—", str(_latest_run(data)["run_key"]) if _latest_run(data) is not None else ""),
        "Reglas bloqueantes fallidas": lambda: _card(_blocking_failed(data), "en las corridas filtradas"),
    }
    if v.kind == "card" and title in figures:
        return figures[title]()
    charts = {
        "Petróleo: producido y proyectado (m³)": lambda: _production_line(data, "oil", v),
        "Gas: producido y proyectado (miles de m³)": lambda: _production_line(data, "gas", v),
        "10 empresas con más petróleo, últimos 12 meses": lambda: _top_companies(data, v),
        "Pozos: ubicación, tamaño por petróleo de 12 meses y color por subtipo": lambda: _wells_scatter(data, v),
        "Suma de P10 por pozo y de P90 por pozo (no son las del total)": lambda: _p10_p90_table(data),
        "Producción por empresa y año": lambda: _company_matrix(data),
        "Petróleo por yacimiento": lambda: _field_treemap(data, v),
        "Yacimientos: pozos, petróleo de 12 meses, P50 de los próximos 12 meses y variación": lambda: _field_rows(data),
        "Petróleo: producido, curva ajustada y P10/P50/P90 por método (m³)": lambda: _well_line(data, v, well),
        "Ajuste de la curva base": lambda: _fit_card(data, well),
        "Últimos 24 meses y 12 proyectados": lambda: _well_table(data, well),
        "WAPE por método y horizonte": lambda: _wape_bars(data, v),
        "Cobertura P10-P90 por horizonte y método, con el objetivo de 0,8": lambda: _coverage_lines(data, v),
        "Series que superan a la línea base": lambda: _beats_bars(data, v),
        "WAPE por método y tramo de edad": lambda: _age_matrix(data),
        "WAPE por origen": lambda: _wape_by_origin(data, v),
        "Reglas de validación": lambda: _rules_table(data),
        "Filas por mes": lambda: _rows_line(data, v),
        "Corridas": lambda: _runs_table(data),
    }
    if title in charts:
        return charts[title]()
    return f'<div class="sub">{escape(", ".join(v.fields))}</div>'


def _well_attr(data: _Data, well: int | None, column: str) -> str:
    wells = data.t["dim_well"].set_index("well_key")
    if well is None or well not in wells.index or pd.isna(wells.loc[well, column]):
        return "—"
    return str(wells.loc[well, column])


# --- sections ---------------------------------------------------------------------------------------------------------


def _steps(model: SemanticModel) -> str:
    dates = next(t for t in model.tables if t.name == "dim_calendar")
    steps = [
        "Instale Power BI Desktop (gratuito, solo para Windows) y abra un informe en blanco.",
        "Cree un parámetro de texto llamado <code>CarpetaSalidas</code> con la ruta de la carpeta <code>outputs\\powerbi</code> de este proyecto.",
        f"Cree una consulta por tabla ({len(model.tables)}) con el código de la sección «Power Query». Cada consulta carga un archivo Parquet; deje el nombre de la consulta igual al de la tabla.",
        f"En la vista de modelo, cree las {len(model.relationships)} relaciones de la tabla «Relaciones»: cardinalidad uno a varios (1:*), dirección del filtro única (de la dimensión al hecho), todas activas. No cree relaciones bidireccionales ni inactivas.",
        f"Marque <code>dim_calendar</code> como tabla de fechas con la columna <code>{dates.columns[2].name}</code>.",
        "Ordene <code>month_name_es</code> por <code>month</code>, <code>year_month_label</code> por <code>period_key</code>, <code>horizon_label</code> por <code>horizon</code> y <code>method_name_es</code> por <code>sort_order</code>. Oculte las columnas de clave de los hechos.",
        "Cree una tabla vacía llamada <code>_Medidas</code> («Especificar datos» sin filas) y agregue en ella las medidas de la sección «Medidas DAX», con su formato.",
        f"Cree las {len(model.pages)} páginas a escala 16:9 (1280 × 720 px) y ubique cada visual según la grilla de 12 columnas de la sección «Las cinco páginas».",
        "Guarde el informe como <code>.pbix</code>. Cuando corra el flujo, vuelva a cargar con «Actualizar»: las consultas leen los mismos archivos.",
    ]
    return "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>"


def _diagram(model: SemanticModel) -> str:
    """Dimensions above and below, facts in the middle row; each relationship a line from "1" to "*" with an arrow."""
    width, height = 1180, 600
    top = ["dim_calendar", "dim_origin", "dim_horizon", "dim_method"]
    bottom = ["dim_well", "dim_company", "dim_fluid", "dim_pipeline_run"]
    facts = [t.name for t in model.tables if t.kind == "fact"]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for names, y, w, h in ((top, 24, 200, 46), (bottom, height - 70, 200, 46), (facts, 270, 150, 56)):
        gap = (width - w * len(names)) / (len(names) + 1)
        for i, name in enumerate(names):
            boxes[name] = (gap + i * (w + gap), y, w, h)
    incoming: dict[tuple[str, str], list[str]] = {}
    for r in model.relationships:
        side = "top" if r.dim_table in top else "bottom"
        incoming.setdefault((r.fact_table, side), []).append(r.rel_id)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" class="model-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Diagrama del modelo en estrella: ocho dimensiones y siete hechos">']
    out.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>')
    counters: dict[tuple[str, str], int] = {}
    outgoing: dict[str, int] = {}
    totals_out: dict[str, int] = {}
    for r in model.relationships:
        totals_out[r.dim_table] = totals_out.get(r.dim_table, 0) + 1
    for r in model.relationships:
        side = "top" if r.dim_table in top else "bottom"
        dx, dy, dw, dh = boxes[r.dim_table]
        fx, fy, fw, fh = boxes[r.fact_table]
        k = outgoing[r.dim_table] = outgoing.get(r.dim_table, 0) + 1
        x1 = dx + dw * k / (totals_out[r.dim_table] + 1)
        y1 = dy + dh if side == "top" else dy
        n = len(incoming[(r.fact_table, side)])
        j = counters[(r.fact_table, side)] = counters.get((r.fact_table, side), 0) + 1
        x2 = fx + fw * j / (n + 1)
        y2 = fy if side == "top" else fy + fh
        out.append(f'<line class="rel" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" marker-end="url(#arrow)"><title>{escape(r.rel_id)}: {escape(r.dim_table)}[{escape(r.dim_column)}] 1 → * {escape(r.fact_table)}[{escape(r.fact_column)}]</title></line>')
        sign = 1 if side == "top" else -1
        out.append(f'<text class="card" x="{x1 + 3:.1f}" y="{y1 + sign * 13:.1f}">1</text>')
        out.append(f'<text class="card" x="{x2 + 3:.1f}" y="{y2 - sign * 6:.1f}">*</text>')
    for name, (x, y, w, h) in boxes.items():
        table = model.table(name)
        cls = "dim" if table.kind == "dimension" else "fact"
        out.append(f'<rect class="box {cls}" x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="6"/>')
        out.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 - 2:.1f}" text-anchor="middle">{escape(name)}</text>')
        key = ", ".join(table.key) if table.kind == "dimension" else f"{len(table.columns)} columnas"
        out.append(f'<text class="small" x="{x + w / 2:.1f}" y="{y + h / 2 + 12:.1f}" text-anchor="middle">{escape(key)}</text>')
    out.append(f'<text class="small" x="8" y="{height - 6}">Cada línea va de la dimensión («1») al hecho («*»); la flecha es la dirección del filtro, única y activa.</text>')
    out.append("</svg>")
    return "".join(out)


def _relationships(model: SemanticModel) -> str:
    rows = [
        [r.rel_id, f"{r.dim_table}[{r.dim_column}]", "1", f"{r.fact_table}[{r.fact_column}]", "*", "Uno a varios (1:*)",
         "Única: de la dimensión al hecho" if r.cross_filter == "single" else r.cross_filter, "Sí" if r.active else "No"]
        for r in model.relationships
    ]
    return _table_html(["ID", "Dimensión", "", "Hecho", "", "Cardinalidad", "Dirección del filtro", "Activa"], rows)


def _queries(model: SemanticModel) -> str:
    parts = []
    for t in model.tables:
        dates = [c.name for c in t.columns if c.dtype == "date"]
        steps = f'    Origen = Parquet.Document(File.Contents(CarpetaSalidas & "\\{t.name}.parquet"))'
        last = "Origen"
        if dates:
            casts = ", ".join(f'{{"{d}", type date}}' for d in dates)
            steps += f",\n    Tipos = Table.TransformColumnTypes(Origen, {{{casts}}})"
            last = "Tipos"
        code = f"let\n{steps}\nin\n    {last}"
        parts.append(f"<h3>{escape(t.name)}</h3><p>{escape(t.description_es)}</p><pre><code>{escape(code)}</code></pre>")
    return "".join(parts)


def _measures(model: SemanticModel) -> str:
    parts = []
    for m in model.measures:
        uses = sorted(dax_measure_refs(m.dax))
        used = f" Usa: {', '.join('[' + u + ']' for u in uses)}." if uses else ""
        parts.append(
            f"<h3>{escape(m.name_es)}</h3><p>{escape(m.description_es)}{escape(used)} Formato: <code>{escape(m.format_string)}</code>.</p>"
            f"<pre><code>{escape(m.name_es)} =\n{escape(m.dax)}</code></pre>"
        )
    return "".join(parts)


def _page_section(data: _Data, page: Page, number: int, well: int | None, attribution: str) -> str:
    visuals = []
    for v in page.visuals:
        style = f"grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"
        body = _preview(data, page, v, well, attribution)
        visuals.append(
            f'<section class="visual" style="{style}" aria-label="{escape(v.title_es)}"><header><b>{escape(v.title_es)}</b>'
            f'<span>{escape(KIND_ES.get(v.kind, v.kind))}</span></header><div class="body">{body}</div></section>'
        )
    rows = [
        [KIND_ES.get(v.kind, v.kind), v.title_es, ", ".join(v.fields) or "—", f"x {v.x}, y {v.y}, ancho {v.w}, alto {v.h}"]
        for v in page.visuals
    ]
    table = _table_html(["Visual", "Título", "Campos", "Posición (celdas)"], rows)
    return (
        f'<h3 id="pagina-{number}">Página {number}: {escape(page.name_es)}</h3>'
        f'<div class="canvas-wrap"><div class="canvas" role="group" aria-label="Página {escape(page.name_es)}">{"".join(visuals)}</div></div>'
        f'<details><summary>Posición, tipo y campos de cada visual</summary><div class="scroll placement">{table}</div></details>'
    )


def _page_html(model: SemanticModel, data: _Data, attribution: str) -> str:
    well = _example_well(data)
    well_name = _well_attr(data, well, "well_code")
    nav = "".join(f'<li><a href="#{key}">{escape(title)}</a></li>' for key, title in SECTIONS)
    pages = "".join(_page_section(data, p, i, well, attribution) for i, p in enumerate(model.pages, start=1))
    coverage = f"{data.wells_forecast} de {data.wells_total}"
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{escape(TITLE)}</h1>
<p class="lead">Guía para armar el informe en Power BI Desktop a partir de los archivos Parquet de <code>outputs/powerbi</code>: modelo, relaciones, consultas, medidas y las cinco páginas con sus visuales ubicados. Las vistas previas usan los números reales de esos archivos.</p>
<div class="meta"><span>Datos hasta <b>{escape(data.label(data.last_key))}</b></span><span>Corrida <code>{escape(data.run_key)}</code></span><span>SHA-256 de la publicación <code>{escape(data.sha[:12])}</code></span><span>Pozos con pronóstico: <b>{escape(coverage)}</b></span><span>Pozo de ejemplo de la página 3: <code>{escape(well_name)}</code></span></div>
<nav aria-label="Secciones"><ul>{nav}</ul></nav>
<h2 id="armado">{escape(SECTIONS[0][1])}</h2>
{_steps(model)}
<div class="warn">La conexión <code>Parquet.Document</code> es la que usa Power BI Desktop para leer archivos Parquet; si su versión no la ofrece, use «Obtener datos» con el conector Parquet y apunte a los mismos archivos.</div>
<h2 id="modelo">{escape(SECTIONS[1][1])}</h2>
<p>Ocho dimensiones alrededor y siete hechos al centro. La jerarquía Provincia, Concesión, Yacimiento, Pozo vive dentro de <code>dim_well</code> (estrella, no copo de nieve). La operadora está en los hechos porque cambia con el tiempo; <code>dim_well[operator_current_name]</code> es solo un atributo.</p>
{_diagram(model)}
<h2 id="relaciones">{escape(SECTIONS[2][1])}</h2>
<div class="scroll">{_relationships(model)}</div>
<h2 id="consultas">{escape(SECTIONS[3][1])}</h2>
{_queries(model)}
<h2 id="medidas">{escape(SECTIONS[4][1])}</h2>
<p>Todas van en la tabla <code>_Medidas</code>. Las de pronóstico se generan por fluido y cuantil con una plantilla; sumar el P10 o el P90 de varios pozos no da el del total, por eso los visuales agregados lo rotulan «Suma de P10 por pozo».</p>
{_measures(model)}
<h2 id="paginas">{escape(SECTIONS[5][1])}</h2>
<p>Cada página es un lienzo de 1280 × 720 px (16:9) sobre una grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas. La posición de cada visual está en celdas: <code>x</code> e <code>y</code> desde la esquina superior izquierda.</p>
{pages}
<h2 id="fuente">{escape(SECTIONS[6][1])}</h2>
<p>{escape(attribution)}</p>
<p>Datos de la corrida <code>{escape(data.run_key)}</code>, hasta {escape(data.label(data.last_key))}. Este documento se genera con <code>python -m oilgas run</code> a partir de <code>dashboard/semantic_model.py</code>; no se edita a mano.</p>
</main>
</body>
</html>
"""


def render_design(model: SemanticModel, outputs_dir: Path, html_path: Path, attribution: str) -> Path:
    """Write the HTML design of the report to `html_path` (atomically) and return the path."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"the semantic model is inconsistent: {problems[0]}")
    data = _Data(outputs_dir, model)
    html = _page_html(model, data, attribution)
    path = write_atomic(html_path, html)
    logger.info("dashboard design written to %s (%d bytes)", path, len(html.encode("utf-8")))
    return path
