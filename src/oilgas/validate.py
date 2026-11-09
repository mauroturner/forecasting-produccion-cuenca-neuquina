"""Validation of the monthly publication against the data contract (RF03, RF04).

Rules V01-V10 are blocking: if one fails the file is rejected. V11-V20 are warnings: the file is
accepted, the affected rows are corrected in SQL where the plan says so and always marked.
I01-I03 only count. Rules that cannot be evaluated because an earlier blocking rule failed (for
example every rule after V01 if the file is not UTF-8) are listed in ``not_evaluated`` instead of
being reported as passed.

``validate_file`` returns the report and, when nothing blocks, the in-scope subset with English
names, typed columns and the raw values (the corrections happen later, in ``sql/``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oilgas.config import PipelineConfig
from oilgas.schema import SOURCE_COLUMNS, USED_COLUMNS, period_index_of, period_index_of_key, read_source_csv

logger = logging.getLogger(__name__)

EXAMPLE_LIMIT = 5
AUTO_LOADED_MARKER = "[Sin movimientos]"  # the published text has a few variants of the words before it
EFFECTIVE_STATE = "Extracción Efectiva"


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


# rule id -> (name in Spanish, severity). The order is the report's order.
RULES: dict[str, tuple[str, Severity]] = {
    "V01": ("El archivo se lee como CSV en UTF-8", Severity.BLOCKING),
    "V02": ("Están todas las columnas que usa el proyecto", Severity.BLOCKING),
    "V03": ("idpozo, anio y mes son enteros y no nulos", Severity.BLOCKING),
    "V04": ("El mes está entre 1 y 12 y el período está dentro del alcance y no es futuro", Severity.BLOCKING),
    "V05": ("fecha_data es el último día del mes de la fila", Severity.BLOCKING),
    "V06": ("La clave (idpozo, anio, mes) es única", Severity.BLOCKING),
    "V07": ("Los volúmenes no convertibles o nulos no superan el umbral", Severity.BLOCKING),
    "V08": ("El subconjunto (cuenca y tipo de recurso) no está vacío", Severity.BLOCKING),
    "V09": ("El subconjunto no se achica respecto de la carga previa", Severity.BLOCKING),
    "V10": ("El último período no es anterior al de la carga previa", Severity.BLOCKING),
    "V11": ("El último período trae filas comparables con las del anterior", Severity.WARNING),
    "V12": ("Volumen negativo (se corrige a nulo)", Severity.WARNING),
    "V13": ("Días efectivos mayores que los días del mes (se corrigen a nulo)", Severity.WARNING),
    "V14": ("Días efectivos en cero con producción (se conserva y se marca)", Severity.WARNING),
    "V15": ("Volumen mensual por encima del tope plausible (se conserva y se marca)", Severity.WARNING),
    "V16": ("Coordenadas intercambiadas o fuera de la cuenca", Severity.WARNING),
    "V17": ("Profundidad fuera de rango (se corrige a nulo)", Severity.WARNING),
    "V18": ("Atributo fijo con más de un valor en un mismo pozo", Severity.WARNING),
    "V19": ("Columnas que no están en el contrato", Severity.WARNING),
    "V20": ("Total de un período antiguo revisado más allá de la tolerancia", Severity.WARNING),
    "I01": ("Meses sin producción con estado de extracción efectiva", Severity.INFO),
    "I02": ("Filas cargadas automáticamente como sin movimientos", Severity.INFO),
    "I03": ("Meses sin fila dentro del período de un pozo", Severity.INFO),
}

SEVERITY_ES = {Severity.BLOCKING: "bloqueante", Severity.WARNING: "advertencia", Severity.INFO: "informativa"}
# Attributes that belong to the well and must not change over its life (V18).
_FIXED_TEXT = (
    "well_code", "province", "concession_code", "concession_name", "field_code", "field_name",
    "formation_code", "formation_name", "sub_resource_type",
)
_FIXED_NUMERIC = ("lon", "lat", "depth_m")


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name_es: str
    severity: Severity
    passed: bool
    rows_affected: int
    wells_affected: int
    examples: list[dict]

    @property
    def status_es(self) -> str:
        if self.passed:
            return "pasa"
        return "falla" if self.severity is Severity.BLOCKING else "advierte"


@dataclass(frozen=True)
class PreviousLoad:
    rows_subset: int
    wells_subset: int
    last_period_key: int
    period_totals: pd.DataFrame  # period_key, oil_m3, gas_thousand_m3


@dataclass(frozen=True)
class ValidationReport:
    run_key: str
    source_sha256: str
    rows_file: int
    rows_subset: int
    wells_subset: int
    first_period_key: int
    last_period_key: int
    results: list[RuleResult]
    not_evaluated: tuple[str, ...] = field(default=())

    @property
    def blocking_failed(self) -> bool:
        return any(r.severity is Severity.BLOCKING and not r.passed for r in self.results)


class ValidationError(RuntimeError):
    """The file was rejected: at least one blocking rule failed."""


# --- helpers ----------------------------------------------------------------------------------------


def _sha256(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block):
            digest.update(chunk)
    return digest.hexdigest()


def _float(series: pd.Series) -> pd.Series:
    """Text to float; what does not convert (and infinities) becomes NaN."""
    out = pd.to_numeric(series, errors="coerce").astype("float64")
    return out.where(np.isfinite(out))


def _whole(series: pd.Series) -> pd.Series:
    """Text to float, keeping only whole numbers (NaN for anything else)."""
    out = _float(series)
    return out.where(out == np.floor(out))


def _days_in_month(year: np.ndarray, month: np.ndarray) -> np.ndarray:
    table = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    leap = (year % 4 == 0) & ((year % 100 != 0) | (year % 400 == 0))
    return table[month - 1] + ((month == 2) & leap)


def _py(value: Any) -> Any:
    """A JSON-friendly Python value from a pandas/numpy scalar."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


_INTEGER_FIELDS = {"well_id", "period_key", "missing_months"}


def _example_value(name: str, value: Any) -> Any:
    value = _py(value)
    return int(value) if name in _INTEGER_FIELDS and isinstance(value, float) else value


def _examples(frame: pd.DataFrame, columns: dict[str, str]) -> list[dict]:
    """Up to EXAMPLE_LIMIT dicts ``{output name: value}`` taken from the first rows of `frame`."""
    head = frame.head(EXAMPLE_LIMIT)
    return [{out: _example_value(out, head[src].iloc[i]) for out, src in columns.items()} for i in range(len(head))]


def _log_verdict(report: ValidationReport) -> None:
    """One line with the verdict and the counts of a validation (RNF12)."""
    blocking = [r.rule_id for r in report.results if r.severity is Severity.BLOCKING and not r.passed]
    warnings = [r.rule_id for r in report.results if r.severity is Severity.WARNING and not r.passed]
    logger.log(
        logging.WARNING if blocking else logging.INFO,
        "validation of %s: %s; rows_file=%d rows_subset=%d wells_subset=%d periods=%d-%d; blocking failed: %s; warnings: %s; not evaluated: %s",
        report.run_key, "rejected" if blocking else "accepted", report.rows_file, report.rows_subset, report.wells_subset,
        report.first_period_key, report.last_period_key, ", ".join(blocking) or "none", ", ".join(warnings) or "none",
        ", ".join(report.not_evaluated) or "none",
    )


# --- validation -------------------------------------------------------------------------------------


def validate_file(
    path: Path,
    cfg: PipelineConfig,
    previous: PreviousLoad | None,
    run_key: str,
    today: date,
) -> tuple[ValidationReport, pd.DataFrame | None]:
    """Validate `path` and return the report and, if no blocking rule failed, the validated subset."""
    path = Path(path)
    source_sha256 = _sha256(path)
    results: dict[str, RuleResult] = {}

    def add(rule_id: str, passed: bool, rows: int = 0, wells: int = 0, examples: list[dict] | None = None) -> None:
        name, severity = RULES[rule_id]
        results[rule_id] = RuleResult(
            rule_id, name, severity, True if severity is Severity.INFO else bool(passed),
            int(rows), int(wells), examples or [],
        )

    def finish(rows_file: int = 0, rows_subset: int = 0, wells: int = 0, first: int = 0, last: int = 0,
               frame: pd.DataFrame | None = None) -> tuple[ValidationReport, pd.DataFrame | None]:
        ordered = [results[i] for i in RULES if i in results]
        report = ValidationReport(
            run_key, source_sha256, rows_file, rows_subset, wells, first, last, ordered,
            tuple(i for i in RULES if i not in results),
        )
        _log_verdict(report)
        return report, (None if report.blocking_failed else frame)

    # V01: the file reads as UTF-8 CSV
    try:
        df = read_source_csv(path)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        add("V01", False, examples=[{"error": f"{type(error).__name__}: {error}"[:300]}])
        return finish()
    add("V01", True)
    rows_file = len(df)

    # V19: columns outside the contract (a warning, evaluable whatever else fails)
    unknown = [c for c in df.columns if c not in SOURCE_COLUMNS]
    add("V19", not unknown, examples=[{"column": c} for c in unknown[:EXAMPLE_LIMIT]])

    # V02: every column the project uses is there
    missing = [c for c in USED_COLUMNS if c not in df.columns]
    add("V02", not missing, examples=[{"column": c} for c in missing[:EXAMPLE_LIMIT]])
    if missing:
        return finish(rows_file)

    # Scope: basin and resource type
    in_scope = (df["cuenca"] == cfg.scope.basin) & (df["tipo_de_recurso"] == cfg.scope.resource_type)
    w = df.loc[in_scope, list(USED_COLUMNS)].rename(columns={k: v[0] for k, v in USED_COLUMNS.items()})
    del df
    w = w.reset_index(drop=True)
    n_rows = len(w)

    add("V08", n_rows > 0)
    if n_rows == 0:
        _rule_v09(add, previous, cfg, 0, 0)
        return finish(rows_file)

    # V03: whole, non-null keys
    year, month, well = _whole(w["year"]), _whole(w["month"]), _whole(w["well_id"])
    ok = year.notna() & month.notna() & well.notna()
    bad = ~ok
    add("V03", not bad.any(), int(bad.sum()), int(w.loc[bad, "well_id"].nunique()),
        _examples(w[bad], {"well_id": "well_id", "year": "year", "month": "month"}))

    pk = (year * 100 + month).where(ok)
    month_ok = month.between(1, 12)
    cal_ok = ok & month_ok & year.between(1900, 2200)
    pidx = period_index_of(year, month).where(cal_ok)

    # V04: month, year range, not in the future
    today_pk = today.year * 100 + today.month
    out_of_range = ok & (~month_ok | (year < cfg.scope.first_year) | (year > today.year) | (pk > today_pk))
    add("V04", not out_of_range.any(), int(out_of_range.sum()), int(well[out_of_range].nunique()),
        _examples(pd.DataFrame({"well_id": well, "period_key": pk})[out_of_range],
                  {"well_id": "well_id", "period_key": "period_key"}))

    # V05: period_end is the last day of the month
    expected = pd.Series(index=w.index, dtype=object)
    if cal_ok.any():
        y = year[cal_ok].astype("int64").to_numpy()
        m = month[cal_ok].astype("int64").to_numpy()
        d = _days_in_month(y, m)
        expected[cal_ok] = [f"{a:04d}-{b:02d}-{c:02d}" for a, b, c in zip(y, m, d, strict=True)]
    wrong_end = cal_ok & (w["period_end"] != expected)
    add("V05", not wrong_end.any(), int(wrong_end.sum()), int(well[wrong_end].nunique()),
        _examples(pd.DataFrame({"well_id": well, "period_key": pk, "value": w["period_end"]})[wrong_end],
                  {"well_id": "well_id", "period_key": "period_key", "value": "value"}))

    # V06: unique (well, year, month)
    keys = pd.DataFrame({"well": well, "year": year, "month": month})[ok]
    surplus = pd.Series(False, index=w.index)
    surplus[keys.index] = keys.duplicated(keep="first")
    add("V06", not surplus.any(), int(surplus.sum()), int(well[surplus].nunique()),
        _examples(pd.DataFrame({"well_id": well, "period_key": pk})[surplus], {"well_id": "well_id", "period_key": "period_key"}))

    # V07: volumes that do not convert or are null
    oil, gas, water = _float(w["oil_m3"]), _float(w["gas_thousand_m3"]), _float(w["water_m3"])
    bad_volume = oil.isna() | gas.isna() | water.isna()
    raw_volumes = w.assign(period_key=pk)[bad_volume]
    add("V07", int(bad_volume.sum()) <= cfg.validation.max_unparseable_volume_share * n_rows,
        int(bad_volume.sum()), int(well[bad_volume].nunique()),
        _examples(raw_volumes, {"well_id": "well_id", "period_key": "period_key", "oil_m3": "oil_m3",
                                "gas_thousand_m3": "gas_thousand_m3", "water_m3": "water_m3"}))

    # V09 / V10: against the previous load
    first_pk = int(pk[cal_ok].min()) if cal_ok.any() else 0
    last_pk = int(pk[cal_ok].max()) if cal_ok.any() else 0
    wells_subset = int(well[ok].nunique())
    _rule_v09(add, previous, cfg, n_rows, wells_subset)
    if previous is None or last_pk >= previous.last_period_key:
        add("V10", True)
    else:
        add("V10", False, examples=[{"last_period_key": last_pk, "previous_last_period_key": previous.last_period_key}])

    # V11: the last period is comparable with the one before
    if cal_ok.any():
        per_period = pidx[cal_ok].value_counts()
        last_idx = int(pidx[cal_ok].max())
        rows_last, rows_prev = int(per_period.get(last_idx, 0)), int(per_period.get(last_idx - 1, 0))
        passed = rows_prev == 0 or rows_last >= cfg.validation.last_period_min_ratio * rows_prev
        add("V11", passed, 0 if passed else rows_prev - rows_last,
            examples=[] if passed else [{"last_period_key": last_pk, "rows_last": rows_last, "rows_previous": rows_prev}])
    else:
        add("V11", True)

    # V12-V15: row-level warnings
    days = pd.Series(np.nan, index=w.index)
    if cal_ok.any():
        days[cal_ok] = _days_in_month(year[cal_ok].astype("int64").to_numpy(), month[cal_ok].astype("int64").to_numpy())
    tef = _float(w["effective_days"])
    producing = (oil > 0) | (gas > 0)
    ceilings = cfg.validation

    def row_rule(rule_id: str, mask: pd.Series, value: pd.Series) -> None:
        frame = pd.DataFrame({"well_id": well, "period_key": pk, "value": value})[mask]
        add(rule_id, not mask.any(), int(mask.sum()), int(well[mask].nunique()),
            _examples(frame, {"well_id": "well_id", "period_key": "period_key", "value": "value"}))

    negative = (oil < 0) | (gas < 0) | (water < 0)
    row_rule("V12", negative, pd.concat([oil, gas, water], axis=1).min(axis=1))
    row_rule("V13", tef > days, tef)
    row_rule("V14", (tef == 0) & producing, tef)
    over_oil, over_gas = oil > ceilings.oil_ceiling_m3, gas > ceilings.gas_ceiling_thousand_m3
    row_rule("V15", over_oil | over_gas, oil.where(over_oil, gas))

    # V16-V18: well-level warnings, on each well's latest row
    attrs = w[list(_FIXED_TEXT)].copy()
    attrs["well_id"], attrs["pk"] = well, pk
    attrs["lon"], attrs["lat"], attrs["depth_m"] = _float(w["lon"]), _float(w["lat"]), _float(w["depth_m"])
    attrs = attrs[ok]
    rows_per_well = attrs["well_id"].value_counts()
    latest = attrs.sort_values("pk", kind="stable").drop_duplicates("well_id", keep="last").set_index("well_id")

    lon_range, lat_range = ceilings.basin_lon, ceilings.basin_lat
    inside = latest["lon"].between(*lon_range) & latest["lat"].between(*lat_range)
    swapped = ~inside & latest["lat"].between(*lon_range) & latest["lon"].between(*lat_range)
    flagged = latest[~inside]
    reason = pd.Series("outside", index=flagged.index)
    reason[swapped[~inside]] = "swapped"
    reason[flagged["lon"].isna() | flagged["lat"].isna()] = "missing"
    add("V16", flagged.empty, int(rows_per_well.reindex(flagged.index).sum()), len(flagged),
        _examples(flagged.assign(reason=reason).reset_index(), {"well_id": "well_id", "lon": "lon", "lat": "lat", "reason": "reason"}))

    low, high = ceilings.depth_valid_m
    bad_depth = latest[latest["depth_m"].notna() & ((latest["depth_m"] < low) | (latest["depth_m"] > high))]
    add("V17", bad_depth.empty, int(rows_per_well.reindex(bad_depth.index).sum()), len(bad_depth),
        _examples(bad_depth.reset_index(), {"well_id": "well_id", "value": "depth_m"}))

    distinct = attrs.groupby("well_id")[[*_FIXED_TEXT, *_FIXED_NUMERIC]].nunique(dropna=True)
    changing = distinct[(distinct > 1).any(axis=1)]
    changed_cols = (changing > 1).apply(lambda row: ",".join(c for c in changing.columns if row[c]), axis=1)
    add("V18", changing.empty, int(rows_per_well.reindex(changing.index).sum()), len(changing),
        _examples(pd.DataFrame({"well_id": changing.index, "attributes": changed_cols.to_numpy()}),
                  {"well_id": "well_id", "attributes": "attributes"}))

    # V20: totals of old periods that moved more than the tolerance
    _rule_v20(add, previous, cfg, pk, pidx, cal_ok, oil, gas, well)

    # Informational
    # A month is idle only when both volumes are known: an unparseable one (NaN) is unknown, not zero (V07 counts it).
    effective_idle = (w["well_status"] == EFFECTIVE_STATE) & ~producing & oil.notna() & gas.notna() & ok
    add("I01", True, int(effective_idle.sum()), int(well[effective_idle].nunique()),
        _examples(pd.DataFrame({"well_id": well, "period_key": pk})[effective_idle], {"well_id": "well_id", "period_key": "period_key"}))
    auto = w["remarks"].fillna("").str.contains(AUTO_LOADED_MARKER, regex=False) & ok
    add("I02", True, int(auto.sum()), int(well[auto].nunique()),
        _examples(pd.DataFrame({"well_id": well, "period_key": pk})[auto], {"well_id": "well_id", "period_key": "period_key"}))
    spans = pd.DataFrame({"well_id": well, "pidx": pidx})[cal_ok].drop_duplicates()
    grouped = spans.groupby("well_id")["pidx"].agg(["min", "max", "count"])
    gaps = (grouped["max"] - grouped["min"] + 1 - grouped["count"]).astype("int64")
    gaps = gaps[gaps > 0]
    add("I03", True, int(gaps.sum()), len(gaps),
        _examples(pd.DataFrame({"well_id": gaps.index, "missing_months": gaps.to_numpy()}),
                  {"well_id": "well_id", "missing_months": "missing_months"}))

    report_ok = not any(r.severity is Severity.BLOCKING and not r.passed for r in results.values())
    frame = _typed_subset(w, year, month, well) if report_ok else None
    return finish(rows_file, n_rows, wells_subset, first_pk, last_pk, frame)


def _rule_v09(add, previous: PreviousLoad | None, cfg: PipelineConfig, rows: int, wells: int) -> None:
    if previous is None:
        add("V09", True)
        return
    enough_rows = rows >= cfg.validation.min_rows_ratio * previous.rows_subset
    enough_wells = wells >= cfg.validation.min_wells_ratio * previous.wells_subset
    add("V09", enough_rows and enough_wells,
        0 if enough_rows else previous.rows_subset - rows, 0 if enough_wells else previous.wells_subset - wells,
        [] if enough_rows and enough_wells else [
            {"rows": rows, "previous_rows": previous.rows_subset, "wells": wells, "previous_wells": previous.wells_subset}
        ])


def _rule_v20(add, previous, cfg, pk, pidx, cal_ok, oil, gas, well) -> None:
    if previous is None or not cal_ok.any():
        add("V20", True)
        return
    new = pd.DataFrame({"period_key": pk[cal_ok], "oil": oil[cal_ok], "gas": gas[cal_ok]}).groupby("period_key").sum()
    old = previous.period_totals.set_index("period_key")[["oil_m3", "gas_thousand_m3"]]
    joined = old.join(new, how="left").fillna({"oil": 0.0, "gas": 0.0})
    last_idx = int(pidx[cal_ok].max())
    age = last_idx - period_index_of_key(joined.index)
    tol = cfg.validation.revision_total_tolerance
    moved = (
        ((joined["oil"] - joined["oil_m3"]).abs() > tol * joined["oil_m3"].abs())
        | ((joined["gas"] - joined["gas_thousand_m3"]).abs() > tol * joined["gas_thousand_m3"].abs())
    ) & (age > cfg.validation.revision_min_age_months)
    flagged = joined[moved].sort_index()
    affected = cal_ok & pk.isin(flagged.index)
    add("V20", flagged.empty, int(affected.sum()), int(well[affected].nunique()), [
        {"period_key": int(p), "previous_oil_m3": _py(r.oil_m3), "new_oil_m3": _py(r.oil),
         "previous_gas_thousand_m3": _py(r.gas_thousand_m3), "new_gas_thousand_m3": _py(r.gas)}
        for p, r in flagged.head(EXAMPLE_LIMIT).iterrows()
    ])


def _typed_subset(w: pd.DataFrame, year: pd.Series, month: pd.Series, well: pd.Series) -> pd.DataFrame:
    """The validated frame: English names, typed columns, values as published."""
    out = pd.DataFrame(index=w.index)
    for english, kind in USED_COLUMNS.values():
        column = w[english]
        if kind == "int":
            out[english] = {"year": year, "month": month, "well_id": well}[english].astype("int64")
        elif kind == "float":
            out[english] = _float(column)
        elif kind == "timestamp":
            out[english] = pd.to_datetime(column, errors="coerce", format="mixed")
        elif kind == "date":
            out[english] = pd.to_datetime(column, errors="coerce", format="%Y-%m-%d")
        elif kind == "flag":
            out[english] = column.map({"t": True, "f": False}).astype(object).where(column.isin(["t", "f"]), None)
        else:
            out[english] = column.astype(object).where(column.notna(), None)
    out["period_key"] = out["year"] * 100 + out["month"]
    out["period_index"] = period_index_of(out["year"], out["month"])
    return out


# --- report files -----------------------------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _report_json(report: ValidationReport) -> str:
    document = {
        "run_key": report.run_key,
        "source_sha256": report.source_sha256,
        "rows_file": report.rows_file,
        "rows_subset": report.rows_subset,
        "wells_subset": report.wells_subset,
        "first_period_key": report.first_period_key,
        "last_period_key": report.last_period_key,
        "blocking_failed": report.blocking_failed,
        "not_evaluated": list(report.not_evaluated),
        "results": [
            {
                "rule_id": r.rule_id,
                "name_es": r.name_es,
                "severity": SEVERITY_ES[r.severity],
                "status": r.status_es,
                "rows_affected": r.rows_affected,
                "wells_affected": r.wells_affected,
                "examples": r.examples,
            }
            for r in report.results
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _report_markdown(report: ValidationReport) -> str:
    verdict = "Rechazado: hay reglas bloqueantes que fallan." if report.blocking_failed else "Aceptado: ninguna regla bloqueante falla."
    lines = [
        "# Reporte de validación",
        "",
        f"- Corrida: `{report.run_key}`",
        f"- Resultado: **{verdict}**",
        f"- SHA-256 del archivo: `{report.source_sha256}`",
        f"- Filas del archivo: {report.rows_file}; filas del subconjunto: {report.rows_subset}; pozos: {report.wells_subset}",
        f"- Períodos del subconjunto: {report.first_period_key} a {report.last_period_key}",
        "",
        "## Reglas",
        "",
        "| ID | Regla | Severidad | Estado | Filas | Pozos |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for r in report.results:
        lines.append(f"| {r.rule_id} | {r.name_es} | {SEVERITY_ES[r.severity]} | {r.status_es} | {r.rows_affected} | {r.wells_affected} |")
    if report.not_evaluated:
        lines += ["", "## No evaluadas", "", "No se pudieron evaluar porque una regla bloqueante anterior falló: "
                  + ", ".join(report.not_evaluated) + "."]
    shown = [r for r in report.results if r.examples and (not r.passed or r.severity is Severity.INFO)]
    if shown:
        lines += ["", "## Ejemplos", ""]
        for r in shown:
            lines += [f"### {r.rule_id}: {r.name_es}", ""]
            lines += [f"- `{json.dumps(e, ensure_ascii=False)}`" for e in r.examples]
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(report: ValidationReport, out_dir: Path) -> tuple[Path, Path]:
    """Write ``latest.json``/``latest.md`` and a copy per run in ``history/``; return the latest pair."""
    out_dir = Path(out_dir)
    text_json, text_md = _report_json(report), _report_markdown(report)
    for directory, stem in ((out_dir, "latest"), (out_dir / "history", report.run_key)):
        _atomic_write(directory / f"{stem}.json", text_json)
        _atomic_write(directory / f"{stem}.md", text_md)
    return out_dir / "latest.json", out_dir / "latest.md"
