"""Backtest summary, the preregistered criteria, method selection and the results block (RF13-RF15).

``summarize`` reduces the evaluation pairs (the long frame of ``backtest.evaluation_pairs``, the same pairs
for every method of a segment) to one row per (method, fluid, horizon, segment): ``model_summary``.
``evaluate_criteria`` applies the thresholds fixed in advance in ``[criteria]`` (AC14-AC16) and words each
verdict from fixed templates, favorable or not: nothing is left out because it reads badly.
``select_methods`` chooses the method that feeds the dashboard's default view (D11). The Markdown is the
block that ``sync_block`` copies into the README.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from oilgas.config import CriteriaConfig, PipelineConfig
from oilgas.files import write_atomic
from oilgas.metrics import bias, coverage, mae, rmse, scaled_pinball, share_beats, wape
from oilgas.series import FLUIDS

SUMMARY_COLUMNS = [
    "method", "fluid", "horizon", "segment", "n_series", "n_points", "mae", "rmse", "wape", "bias", "coverage",
    "scaled_pinball", "share_beats_naive_last", "share_beats_naive_mean3", "fallback_rate", "basin_band_coverage",
    "coverage_verdict", "verdict_es",
]
SELECTION_COLUMNS = ["fluid", "segment", "method", "criterion_value", "rule"]
GROUP = ["method", "fluid", "horizon", "segment"]
BASELINE_COLUMNS = {"naive_last": "share_beats_naive_last", "naive_mean3": "share_beats_naive_mean3"}
ARPS = "arps_mh_b2"
ML = "ml_hgb"
# Candidates of the default view per segment (an Arps curve needs an eligible series), simplest first on a tie.
CANDIDATES = {"eligible": (ARPS, ML, "naive_mean3"), "young": (ML, "naive_mean3")}
SIMPLEST_FIRST = ("naive_mean3", ARPS, ML)
SELECTION_RULE = "menor pinball escalada promedio en los horizontes {horizons}; en un empate, el método más simple"
METHOD_ES = {
    "naive_last": "repetir el último mes",
    "naive_mean3": "el promedio de los últimos 3 meses",
    "arps_exp": "la curva exponencial",
    "arps_mh_b2": "la curva de Arps",
    "arps_mh_b1": "la curva de Arps con b hasta 1",
    "ml_hgb": "el modelo de machine learning",
}
FLUID_ES = {"oil": "petróleo", "gas": "gas"}
SEGMENT_ES = {"eligible": "elegibles", "young": "jóvenes"}
VERDICT_WORDS = ("calibrado", "aceptable", "descalibrado")
TIE_TOLERANCE = 1e-12


# --- number and text helpers ----------------------------------------------------------------------------------


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))


def _number(value) -> float | None:
    """A finite float, or None for anything missing."""
    if _is_missing(value):
        return None
    value = float(value)
    return value if np.isfinite(value) else None


def _decimal(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _percent(fraction: float) -> str:
    """A share as Spanish text: no decimals when it is a whole number, more only if rounding would hide it."""
    value = fraction * 100.0
    text = f"{value:.0f}"
    for digits in (0, 1, 2):
        text = f"{value:.{digits}f}"
        if abs(float(text) - value) < 0.005:
            break
    return text.replace(".", ",")


def _method_label(method: str) -> str:
    return METHOD_ES.get(method, method)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _months(horizon: int) -> str:
    return "1 mes" if horizon == 1 else f"{horizon} meses"


def _clean(sentence: str) -> str:
    """Spanish contractions of the templates: "de el" is "del" and "a el" is "al"."""
    return sentence.replace(" de el ", " del ").replace(" a el ", " al ")


def coverage_verdict(value: float, criteria: CriteriaConfig) -> str | None:
    """``calibrado``, ``aceptable`` or ``descalibrado`` for a P10-P90 coverage (AC15); None if there is none."""
    number = _number(value)
    if number is None:
        return None
    if criteria.coverage_calibrated[0] <= number <= criteria.coverage_calibrated[1]:
        return VERDICT_WORDS[0]
    if criteria.coverage_acceptable[0] <= number <= criteria.coverage_acceptable[1]:
        return VERDICT_WORDS[1]
    return VERDICT_WORDS[2]


# --- summary --------------------------------------------------------------------------------------------------


def _share_columns(frame: pd.DataFrame) -> dict[tuple, float]:
    """``{(column, method, fluid, horizon, segment): share}`` of series that beat each baseline present."""
    shares: dict[tuple, float] = {}
    methods = sorted(frame["method"].unique())
    for baseline, column in BASELINE_COLUMNS.items():
        if baseline not in methods:
            continue
        for method in methods:
            if method == baseline:
                continue
            result = share_beats(frame, method, baseline, by=["fluid", "horizon", "segment"])
            for record in result.itertuples(index=False):
                shares[(column, method, record.fluid, int(record.horizon), record.segment)] = float(record.share)
    return shares


def _row_verdict(row: dict) -> str:
    """One sentence about a cell: how it compares with repeating the last month, and its coverage."""
    share = _number(row["share_beats_naive_last"])
    subject = _capitalize(_method_label(row["method"]))
    if row["method"] == "naive_last":
        comparison = "es la línea base de referencia"
    elif share is None:
        comparison = "no tiene comparación con repetir el último mes"
    elif share > 0.5:
        comparison = f"supera a repetir el último mes en el {_percent(share)} % de los pozos"
    else:
        comparison = f"no supera a repetir el último mes: lo hace en el {_percent(share)} % de los pozos"
    where = f"{FLUID_ES.get(row['fluid'], row['fluid'])}, {_months(row['horizon'])}, series {SEGMENT_ES.get(row['segment'], row['segment'])}"
    verdict = row["coverage_verdict"]
    cover = "sin cobertura" if verdict is None else f"cobertura P10-P90 {_decimal(row['coverage'])} ({verdict})"
    return _clean(f"{subject} {comparison} ({where}); {cover}.")


def summarize(forecasts: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    """``model_summary`` rows from the evaluation pairs (``fluid, well_id, origin, horizon, method, segment, actual, p10, p50, p90, fit_status``)."""
    if forecasts.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    frame = forecasts.copy()
    for column in ("fluid", "method", "segment", "fit_status"):
        frame[column] = frame[column].astype(str)
    for column in ("horizon", "well_id", "origin"):
        frame[column] = frame[column].astype(np.int64)
    shares = _share_columns(frame)
    rows = []
    for (method, fluid, horizon, segment), group in frame.groupby(GROUP, sort=True):
        y, p10, p50, p90 = (group[c].to_numpy(dtype=np.float64) for c in ("actual", "p10", "p50", "p90"))
        totals = group.groupby("origin")[["actual", "p10", "p90"]].sum()
        basin = float(((totals["p10"] <= totals["actual"]) & (totals["actual"] <= totals["p90"])).mean())
        if method.startswith("arps"):  # a fit serves every horizon of its origin: count each fit once
            fits = group.drop_duplicates(["well_id", "origin"])
            fallback = float((fits["fit_status"] != "ok").mean())
        else:
            fallback = float("nan")
        row = {
            "method": method, "fluid": fluid, "horizon": int(horizon), "segment": segment,
            "n_series": int(group["well_id"].nunique()), "n_points": int(len(group)),
            "mae": mae(y, p50), "rmse": rmse(y, p50), "wape": wape(y, p50), "bias": bias(y, p50),
            "coverage": coverage(y, p10, p90), "scaled_pinball": scaled_pinball(y, p10, p50, p90),
            "share_beats_naive_last": shares.get(("share_beats_naive_last", method, fluid, int(horizon), segment), float("nan")),
            "share_beats_naive_mean3": shares.get(("share_beats_naive_mean3", method, fluid, int(horizon), segment), float("nan")),
            "fallback_rate": fallback, "basin_band_coverage": basin,
        }
        row["coverage_verdict"] = coverage_verdict(row["coverage"], cfg.criteria)
        row["verdict_es"] = _row_verdict(row)
        rows.append(row)
    return pd.DataFrame(rows)[SUMMARY_COLUMNS]


# --- criteria -------------------------------------------------------------------------------------------------


def _cell(summary: pd.DataFrame, method: str, fluid: str, horizon: int, segment: str) -> pd.Series | None:
    hit = summary[
        (summary["method"] == method) & (summary["fluid"] == fluid) & (summary["horizon"] == horizon) & (summary["segment"] == segment)
    ]
    return hit.iloc[0] if len(hit) else None


def _value(cell: pd.Series | None, column: str) -> float | None:
    return None if cell is None else _number(cell[column])


def _ac14(summary: pd.DataFrame, fluid: str, criteria: CriteriaConfig) -> dict:
    """Arps against repeating the last month: share of series at one horizon and WAPE at others (AC14)."""
    horizon, minimum = criteria.share_beats_horizon, criteria.share_beats_naive_min
    arps_cell = _cell(summary, ARPS, fluid, horizon, "eligible")
    share = _value(arps_cell, "share_beats_naive_last")
    share_passed = share is not None and share >= minimum
    sentences = []
    if share is None:
        sentences.append(
            f"A {_months(horizon)} no hay datos para comparar la curva de Arps con repetir el último mes (sin datos): no se puede afirmar que la supere."
        )
    elif share_passed:
        sentences.append(
            f"A {_months(horizon)}, la curva de Arps supera a repetir el último mes en el {_percent(share)} % de los pozos (umbral: {_percent(minimum)} %)."
        )
    else:
        sentences.append(
            f"A {_months(horizon)}, la curva de Arps no supera a repetir el último mes: lo hace en el {_percent(share)} % de los pozos (umbral: {_percent(minimum)} %)."
        )
    wapes = []
    for h in criteria.wape_horizons:
        arps_wape = _value(_cell(summary, ARPS, fluid, h, "eligible"), "wape")
        naive_wape = _value(_cell(summary, "naive_last", fluid, h, "eligible"), "wape")
        passed = arps_wape is not None and naive_wape is not None and arps_wape < naive_wape
        wapes.append({"horizon": int(h), ARPS: arps_wape, "naive_last": naive_wape, "passed": passed})
        if arps_wape is None or naive_wape is None:
            sentences.append(f"A {_months(h)} no hay datos para comparar el WAPE de la curva de Arps con el de repetir el último mes (sin datos): no se puede afirmar que la supere.")
        elif passed:
            sentences.append(
                f"A {_months(h)}, el WAPE de la curva de Arps ({_percent(arps_wape)} %) es menor que el de repetir el último mes ({_percent(naive_wape)} %)."
            )
        else:
            sentences.append(
                f"A {_months(h)}, el WAPE de la curva de Arps ({_percent(arps_wape)} %) no es menor que el de repetir el último mes ({_percent(naive_wape)} %): no supera a repetir el último mes en WAPE."
            )
    wape_passed = all(w["passed"] for w in wapes)
    return {
        "share_beats_naive_last": share, "share_horizon": int(horizon), "share_threshold": minimum,
        "share_passed": bool(share_passed), "wape": wapes, "wape_passed": bool(wape_passed),
        "passed": bool(share_passed and wape_passed), "verdict_es": sentences,
    }


def _horizons(summary: pd.DataFrame, fluid: str, segment: str) -> list[int]:
    rows = summary[(summary["fluid"] == fluid) & (summary["segment"] == segment)]
    return sorted({int(h) for h in rows["horizon"]})


def _ac15(summary: pd.DataFrame, criteria: CriteriaConfig) -> list[dict]:
    """The coverage verdict of Arps and of the machine-learning model at each fluid and horizon (AC15)."""
    entries = []
    for fluid in FLUIDS:
        for horizon in _horizons(summary, fluid, "eligible"):
            for method in (ARPS, ML):
                value = _value(_cell(summary, method, fluid, horizon, "eligible"), "coverage")
                if value is None:
                    continue
                verdict = coverage_verdict(value, criteria)
                sentence = _clean(
                    f"A {_months(horizon)}, la cobertura P10-P90 de {_method_label(method)} en {FLUID_ES[fluid]} es {_decimal(value)} "
                    f"(objetivo {_decimal(criteria.coverage_target)}): {verdict}."
                )
                entries.append({"fluid": fluid, "horizon": int(horizon), "method": method, "coverage": value, "verdict": verdict, "verdict_es": sentence})
    return entries


def _ac16(summary: pd.DataFrame) -> list[dict]:
    """Whether the machine-learning model beats the simpler method on each segment, by scaled pinball (AC16)."""
    entries = []
    for fluid in FLUIDS:
        for segment, baseline in (("eligible", ARPS), ("young", "naive_mean3")):
            for horizon in _horizons(summary, fluid, segment):
                ml = _value(_cell(summary, ML, fluid, horizon, segment), "scaled_pinball")
                other = _value(_cell(summary, baseline, fluid, horizon, segment), "scaled_pinball")
                if ml is None or other is None:
                    continue
                better = ml < other
                verb = "supera" if better else "no supera"
                sentence = _clean(
                    f"A {_months(horizon)}, en {FLUID_ES[fluid]} (series {SEGMENT_ES[segment]}), el modelo de machine learning {verb} a "
                    f"{_method_label(baseline)} (pinball escalada {_decimal(ml)} frente a {_decimal(other)})."
                )
                entries.append({
                    "fluid": fluid, "horizon": int(horizon), "segment": segment, "baseline": baseline, "ml_pinball": ml,
                    "baseline_pinball": other, "ml_better": bool(better), "verdict_es": sentence,
                })
    return entries


def _fallback(summary: pd.DataFrame, criteria: CriteriaConfig) -> list[dict]:
    entries = []
    for fluid in FLUIDS:
        for method in sorted(m for m in summary["method"].unique() if str(m).startswith("arps")):
            rates = summary[(summary["fluid"] == fluid) & (summary["method"] == method)]["fallback_rate"].dropna()
            if rates.empty:
                continue
            rate = float(rates.max())
            ok = rate < criteria.max_fallback_rate
            tail = "dentro del máximo" if ok else "supera el máximo"
            sentence = (
                f"La tasa de respaldo de {method} en {FLUID_ES[fluid]} llega a {_percent(rate)} % (máximo: {_percent(criteria.max_fallback_rate)} %): {tail}."
            )
            entries.append({"fluid": fluid, "method": method, "rate": rate, "threshold": criteria.max_fallback_rate, "passed": bool(ok), "verdict_es": sentence})
    return entries


def evaluate_criteria(summary: pd.DataFrame, criteria: CriteriaConfig) -> dict:
    """The preregistered booleans of AC14-AC16 and the fallback rate, with their sentences (JSON-friendly)."""
    ac14 = {fluid: _ac14(summary, fluid, criteria) for fluid in FLUIDS}
    fallback = _fallback(summary, criteria)
    thresholds = {k: (list(v) if isinstance(v, tuple) else v) for k, v in dataclasses.asdict(criteria).items()}
    return {
        "thresholds": thresholds,
        "AC14": ac14,
        "AC15": _ac15(summary, criteria),
        "AC16": _ac16(summary),
        "fallback": fallback,
        "passed": {"AC14": {fluid: ac14[fluid]["passed"] for fluid in FLUIDS}, "fallback": all(f["passed"] for f in fallback)},
    }


# --- method selection -----------------------------------------------------------------------------------------


def select_methods(summary: pd.DataFrame) -> pd.DataFrame:
    """Per fluid and segment, the candidate with the lowest mean scaled pinball over the horizons (D11)."""
    rows = []
    for fluid in FLUIDS:
        for segment, candidates in CANDIDATES.items():
            scope = summary[(summary["fluid"] == fluid) & (summary["segment"] == segment)]
            values = {}
            for method in candidates:
                pinball = scope[scope["method"] == method]["scaled_pinball"].dropna()
                if not pinball.empty:
                    values[method] = float(pinball.mean())
            if not values:
                continue
            best = min(values.values())
            tied = [m for m in SIMPLEST_FIRST if m in values and values[m] <= best + TIE_TOLERANCE * max(1.0, abs(best))]
            horizons = sorted({int(h) for h in scope["horizon"]})
            rows.append({
                "fluid": fluid, "segment": segment, "method": tied[0], "criterion_value": values[tied[0]],
                "rule": SELECTION_RULE.format(horizons=", ".join(str(h) for h in horizons)),
            })
    return pd.DataFrame(rows, columns=SELECTION_COLUMNS)


# --- results block and files ----------------------------------------------------------------------------------


def _wape_table(summary: pd.DataFrame, fluid: str) -> list[str]:
    rows = summary[(summary["fluid"] == fluid) & (summary["segment"] == "eligible")]
    horizons = sorted({int(h) for h in rows["horizon"]})
    if not horizons:
        return [f"Sin datos de {FLUID_ES[fluid]} en las series elegibles."]
    lines = ["| Método | " + " | ".join(_months(h) for h in horizons) + " |", "| --- | " + " | ".join("---:" for _ in horizons) + " |"]
    for method in sorted(rows["method"].unique()):
        cells = []
        for h in horizons:
            value = _value(_cell(summary, method, fluid, h, "eligible"), "wape")
            cells.append("—" if value is None else f"{_percent(value)} %")
        lines.append(f"| {method} | " + " | ".join(cells) + " |")
    return lines


def render_results_markdown(criteria: dict, summary: pd.DataFrame) -> str:
    """The results block of the README: every verdict in words, the WAPE tables and the method in use."""
    lines = ["### Curva de Arps frente a repetir el último mes", ""]
    for fluid in FLUIDS:
        result = criteria["AC14"][fluid]
        lines.append(f"**{_capitalize(FLUID_ES[fluid])}.** {'Cumple' if result['passed'] else 'No cumple'} el criterio fijado de antemano.")
        lines += [f"- {sentence}" for sentence in result["verdict_es"]]
        lines.append("")
    thresholds = criteria["thresholds"]
    lines += [
        "### Cobertura de las bandas P10-P90", "",
        f"Objetivo {_decimal(thresholds['coverage_target'])}: calibrado entre {_decimal(thresholds['coverage_calibrated'][0])} y "
        f"{_decimal(thresholds['coverage_calibrated'][1])}, aceptable entre {_decimal(thresholds['coverage_acceptable'][0])} y "
        f"{_decimal(thresholds['coverage_acceptable'][1])}, descalibrado fuera de ese rango.", "",
    ]
    lines += [f"- {entry['verdict_es']}" for entry in criteria["AC15"]] or ["- Sin datos de cobertura (sin datos)."]
    lines += ["", "### Aporte del machine learning", ""]
    lines += [f"- {entry['verdict_es']}" for entry in criteria["AC16"]] or ["- Sin datos para comparar el machine learning (sin datos)."]
    lines += ["", "### Tasa de respaldo de las curvas de Arps", ""]
    lines += [f"- {entry['verdict_es']}" for entry in criteria["fallback"]] or ["- Sin datos de la tasa de respaldo (sin datos)."]
    lines += ["", "### WAPE por método y horizonte (series elegibles)", ""]
    for fluid in FLUIDS:
        lines += [f"**{_capitalize(FLUID_ES[fluid])}.**", "", *_wape_table(summary, fluid), ""]
    lines += ["### Método en uso por defecto", ""]
    chosen = select_methods(summary)
    if chosen.empty:
        lines.append("Sin datos para elegir el método (sin datos).")
    else:
        lines += ["| Fluido | Series | Método | Pinball escalada promedio |", "| --- | --- | --- | ---: |"]
        for record in chosen.itertuples(index=False):
            lines.append(f"| {_capitalize(FLUID_ES[record.fluid])} | {SEGMENT_ES[record.segment]} | {record.method} | {_decimal(record.criterion_value, 3)} |")
        lines += ["", f"Regla: {chosen.iloc[0]['rule']}."]
    return "\n".join(lines).rstrip("\n") + "\n"


def _json_value(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_summary(criteria: dict, summary: pd.DataFrame, reports_dir: Path) -> tuple[Path, Path]:
    """Write ``backtest_summary.json`` and ``.md`` atomically; the Markdown is the README's results block."""
    reports_dir = Path(reports_dir)
    records = [{k: _json_value(v) for k, v in row.items()} for row in summary.astype(object).to_dict("records")]
    document = {"criteria": criteria, "summary": records}
    text = json.dumps(document, indent=2, ensure_ascii=False, default=_json_value, allow_nan=False) + "\n"
    json_path = write_atomic(reports_dir / "backtest_summary.json", text)
    md_path = write_atomic(reports_dir / "backtest_summary.md", render_results_markdown(criteria, summary))
    return json_path, md_path


def sync_block(path: Path, start_marker: str, end_marker: str, content: str) -> bool:
    """Replace what lies between the two markers of a file with `content`; True if the file changed.

    The file must have exactly one start marker followed by exactly one end marker, otherwise nothing is
    written. Repeating it with the same content changes nothing.
    """
    path = Path(path)
    text = path.read_bytes().decode("utf-8")
    if text.count(start_marker) != 1 or text.count(end_marker) != 1 or text.index(start_marker) > text.index(end_marker):
        raise ValueError(f"{path} needs exactly one {start_marker!r} marker followed by one {end_marker!r} marker")
    head_end = text.index(start_marker) + len(start_marker)
    updated = text[:head_end] + "\n" + content.strip("\n") + "\n" + text[text.index(end_marker):]
    if updated == text:
        return False
    write_atomic(path, updated)
    return True


# --- storage ---------------------------------------------------------------------------------------------------


def _db_value(value):
    return None if _is_missing(value) else (int(value) if isinstance(value, (np.integer,)) else value)


def store_summary(conn: sqlite3.Connection, summary: pd.DataFrame, selection: pd.DataFrame, run_key: str) -> None:
    """Replace ``model_summary`` and ``model_selection`` with the new run in one transaction."""
    summary_rows = [
        (*(_db_value(row[c]) for c in GROUP), run_key, *(_db_value(row[c]) for c in SUMMARY_COLUMNS if c not in GROUP))
        for row in summary.astype(object).to_dict("records")
    ]
    names = [*GROUP, "run_key", *(c for c in SUMMARY_COLUMNS if c not in GROUP)]
    selection_rows = [
        (row["fluid"], row["segment"], run_key, row["method"], _db_value(row["criterion_value"]), row["rule"])
        for row in selection.astype(object).to_dict("records")
    ]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM model_summary")
        conn.execute("DELETE FROM model_selection")
        conn.executemany(f"INSERT INTO model_summary ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", summary_rows)
        conn.executemany(
            "INSERT INTO model_selection (fluid, segment, run_key, method, criterion_value, rule) VALUES (?, ?, ?, ?, ?, ?)",
            selection_rows,
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def read_summary(conn: sqlite3.Connection) -> pd.DataFrame:
    """``model_summary`` in the order of ``SUMMARY_COLUMNS``."""
    return pd.read_sql_query(f"SELECT {', '.join(SUMMARY_COLUMNS)} FROM model_summary ORDER BY {', '.join(GROUP)}", conn)


def read_selection(conn: sqlite3.Connection) -> pd.DataFrame:
    """``model_selection`` in the order of ``SELECTION_COLUMNS``."""
    return pd.read_sql_query(f"SELECT {', '.join(SELECTION_COLUMNS)} FROM model_selection ORDER BY fluid, segment", conn)
