"""Generator of synthetic publications shaped like the real file (40 columns, BOM, same formats).

``make_fixture`` writes about 60 in-scope wells whose oil and gas follow modified hyperbolic curves of
known parameters with lognormal noise (sigma = 0.1), plus every awkward case the pipeline must handle:
partial first months, zero months, missing months, young and stopped wells, a negative gas volume, an
impossible ``tef``, swapped coordinates, invalid depths, operator changes and wells outside the
scope. ``FixtureTruth`` says where each one is. ``make_malformed`` damages a valid file in one of
nine ways, each meant to trip a specific validation rule.

Run as a script: ``python tests/fixtures/make_fixture.py OUT.csv [--wells 60] [--seed 0]``.
"""

from __future__ import annotations

import calendar
import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SOURCE_COLUMNS = (
    "idempresa", "anio", "mes", "idpozo", "prod_pet", "prod_gas", "prod_agua",
    "iny_agua", "iny_gas", "iny_co2", "iny_otro", "tef", "vida_util",
    "tipoextraccion", "tipoestado", "tipopozo", "observaciones", "fechaingreso",
    "rectificado", "habilitado", "idusuario", "empresa", "sigla", "formprod",
    "profundidad", "formacion", "idareapermisoconcesion", "areapermisoconcesion",
    "idareayacimiento", "areayacimiento", "cuenca", "provincia", "coordenadax",
    "coordenaday", "tipo_de_recurso", "proyecto", "clasificacion", "subclasificacion",
    "sub_tipo_recurso", "fecha_data",
)
_COL = {name: i for i, name in enumerate(SOURCE_COLUMNS)}

D_LIM = -float(np.log(1 - 0.10)) / 12  # 10 % effective annual, nominal per month
NOISE_SIGMA = 0.1
AUTO_REMARK = "Cargado automáticamente como [Sin movimientos]"
EFFECTIVE = "Extracción Efectiva"
STOPPED = "Parado Transitoriamente"

MALFORMED_KINDS = (
    "missing_column",
    "renamed_column",
    "non_numeric_well_id",
    "month_13",
    "duplicate_key",
    "bad_period_end",
    "truncated",
    "regressed_last_period",
    "not_utf8",
)

OPERATORS = (
    ("YPF", "YPF S.A.", "334"),
    ("VISTA", "VISTA ENERGY ARGENTINA S.A.U.", "412"),
    ("PAE", "PAN AMERICAN ENERGY SL", "377"),
    ("TECP", "TECPETROL S.A.", "290"),
    ("SHEL", "SHELL ARGENTINA S.A.", "351"),
    ("PLUS", "PLUSPETROL S.A.", "268"),
)
# (concession code, concession name, field code, field name, province)
FIELDS = (
    ("LCLL", "LOMA CAMPANA", "LCAM", "LOMA CAMPANA", "Neuquén"),
    ("ACH", "LA AMARGA CHICA", "LACH", "LA AMARGA CHICA", "Neuquén"),
    ("BDP", "BAJADA DEL PALO", "BDPO", "BAJADA DEL PALO OESTE", "Neuquén"),
    ("SDD", "AL SUR DE LA DORSAL", "RQC", "RANQUIL CO", "Neuquén"),
    ("CHSN", "CHIHUIDO DE LA SIERRA NEGRA", "CSNE", "CHIHUIDO SIERRA NEGRA", "Rio Negro"),
    ("MLG", "MALARGUE", "MLGE", "MALARGUE ESTE", "Mendoza"),
)
EXTRACTION = ("Surgencia Natural", "Plunger Lift", "Bombeo Mecánico", "Gas Lift")


def modified_hyperbolic_rate(t, qi: float, di: float, b: float, d_lim: float = D_LIM) -> np.ndarray:
    """Rate at time `t` (months) of the modified hyperbolic: hyperbolic until the nominal decline
    falls to `d_lim`, exponential after. With `di <= d_lim` it is purely exponential."""
    t = np.asarray(t, dtype=float)
    if di <= d_lim:
        return qi * np.exp(-di * t)
    t_switch = (di / d_lim - 1.0) / (b * di)
    q_switch = qi * (1.0 + b * di * t_switch) ** (-1.0 / b)
    hyper = qi * (1.0 + b * di * np.minimum(t, t_switch)) ** (-1.0 / b)
    return np.where(t <= t_switch, hyper, q_switch * np.exp(-d_lim * (t - t_switch)))


@dataclass(frozen=True)
class CurveTruth:
    """Parameters of one fluid's curve; ``modified_hyperbolic_rate(t, **params)`` gives its rate."""

    params: dict[str, float]


@dataclass(frozen=True)
class WellTruth:
    well_id: int
    well_code: str
    kind: str  # regular | shutin | gap | stopped | young
    sub_resource_type: str
    first_period_key: int
    last_period_key: int
    oil: CurveTruth
    gas: CurveTruth


@dataclass(frozen=True)
class FixtureTruth:
    path: Path
    n_wells: int
    n_rows: int
    n_rows_subset: int
    first_period_key: int
    last_period_key: int
    wells: dict[int, WellTruth]
    out_of_scope_wells: list[int]
    negative_gas_rows: list[tuple[int, int]]
    tef_gt_days_rows: list[tuple[int, int]]
    tef_zero_with_production_rows: list[tuple[int, int]]
    volume_ceiling_rows: list[tuple[int, int]]
    zero_month_rows: list[tuple[int, int]]
    effective_state_zero_rows: list[tuple[int, int]]
    auto_loaded_rows: list[tuple[int, int]]
    missing_month_rows: list[tuple[int, int]]
    swapped_coords_well: int
    depth_invalid_wells: list[int]
    operator_change_wells: list[int]
    notes: dict[str, str] = field(default_factory=dict)


def _fmt(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _key(year: int, month: int) -> int:
    return year * 100 + month


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def _from_index(index: int) -> tuple[int, int]:
    return index // 12, index % 12 + 1


def make_fixture(
    path: Path,
    n_wells: int = 60,
    first: tuple[int, int] = (2018, 1),
    last: tuple[int, int] = (2024, 12),
    seed: int = 0,
) -> FixtureTruth:
    """Write a valid synthetic publication to `path` and return what it contains."""
    rng = np.random.default_rng(seed)
    first_index, last_index = _month_index(*first), _month_index(*last)
    n_months = last_index - first_index + 1
    if n_months < 12:
        raise ValueError("the fixture needs at least 12 months")

    n_young = max(1, n_wells // 10)
    n_stopped = max(1, n_wells // 15)
    kinds: list[str] = []
    for i in range(n_wells):
        if i >= n_wells - n_young:
            kinds.append("young")
        elif i >= n_wells - n_young - n_stopped:
            kinds.append("stopped")
        elif i % 7 == 3:
            kinds.append("shutin")
        elif i % 11 == 5:
            kinds.append("gap")
        else:
            kinds.append("regular")
    regular_ids = [100_001 + i for i, k in enumerate(kinds) if k == "regular"]
    pick = {name: (regular_ids[i] if i < len(regular_ids) else None) for i, name in enumerate(
        ["negative", "tef_over", "tef_zero_a", "tef_zero_b", "swapped", "depth_zero", "depth_high", "op_a", "op_b"]
    )}

    truth_lists: dict[str, list] = {
        "negative_gas_rows": [], "tef_gt_days_rows": [], "tef_zero_with_production_rows": [],
        "zero_month_rows": [], "effective_state_zero_rows": [], "auto_loaded_rows": [],
        "missing_month_rows": [],
    }
    operator_changes: list[int] = []
    rows: list[list[str]] = []
    wells: dict[int, WellTruth] = {}
    young_seen = 0
    shutin_seen = 0

    for i in range(n_wells):
        well_id = 100_001 + i
        kind = kinds[i]
        tight = i % 3 == 0
        sub_type = "TIGHT" if tight else "SHALE"
        if tight:
            oil_qi = float(rng.uniform(4, 30))
            gas_qi = float(rng.uniform(60, 400))
        else:
            oil_qi = float(np.clip(np.exp(rng.normal(np.log(150), 0.7)), 20, 900))
            gas_qi = oil_qi * float(rng.uniform(0.3, 1.5))
        di = float(rng.uniform(0.08, 0.35))
        b = float(rng.uniform(0.5, 1.8))
        gas_di = di * float(rng.uniform(0.6, 1.0))
        water_qi = oil_qi * float(rng.uniform(0.2, 1.0))
        oil_curve = {"qi": oil_qi, "di": di, "b": b, "d_lim": D_LIM}
        gas_curve = {"qi": gas_qi, "di": gas_di, "b": b, "d_lim": D_LIM}

        if kind == "young":
            length = 3 + young_seen % 3
            young_seen += 1
            start = n_months - length
            end = n_months - 1
        elif kind == "stopped":
            start = int(rng.integers(0, 10))
            end = n_months - 11
        else:
            start = (i * 7) % max(1, n_months - 30)
            end = n_months - 1
        length = end - start + 1

        field_info = FIELDS[i % len(FIELDS)]
        operator = OPERATORS[i % len(OPERATORS)]
        other_operator = OPERATORS[(i + 3) % len(OPERATORS)]
        formation = ("VMUT", "vaca muerta") if not tight else (("LAJA", "lajas") if i % 2 else ("MULI", "mulichinco"))
        lon = float(rng.uniform(-70.5, -68.0))
        lat = float(rng.uniform(-39.5, -37.5))
        depth = float(round(rng.uniform(2500, 4500)))
        extraction = EXTRACTION[i % len(EXTRACTION)]
        well_code = f"SYN.Nq.{field_info[2]}.x-{i + 1}"
        if well_id == pick["swapped"]:
            lon, lat = lat, lon
        depth_text = _fmt(depth)
        if well_id == pick["depth_zero"]:
            depth_text = "0"
        elif well_id == pick["depth_high"]:
            depth_text = "9000"

        zero_at: set[int] = set()
        missing_at: set[int] = set()
        if kind == "shutin":
            zero_at = {length // 2, length // 2 + 1}
        elif kind == "gap":
            missing_at = {length // 2, length // 2 + 1} if i % 2 else {length // 2}
        first_shutin = kind == "shutin" and shutin_seen == 0
        auto_shutin = kind == "shutin" and shutin_seen % 2 == 1
        if kind == "shutin":
            shutin_seen += 1
        if well_id in (pick["op_a"], pick["op_b"]):
            operator_changes.append(well_id)

        for k in range(length):
            year, month = _from_index(first_index + start + k)
            days = calendar.monthrange(year, month)[1]
            pk = _key(year, month)
            if k in missing_at:
                truth_lists["missing_month_rows"].append((well_id, pk))
                continue
            if k == 0:
                factor_oil = factor_gas = 0.5
                water_rate = water_qi * 0.5
            else:
                t = float(k - 1)
                factor_oil = float(modified_hyperbolic_rate(t, **oil_curve)) / oil_qi
                factor_gas = float(modified_hyperbolic_rate(t, **gas_curve)) / gas_qi
                water_rate = water_qi * float(np.exp(-0.01 * t))
            oil = oil_qi * factor_oil * days * float(np.exp(rng.normal(0, NOISE_SIGMA)))
            gas = gas_qi * factor_gas * days * float(np.exp(rng.normal(0, NOISE_SIGMA)))
            water = water_rate * days * float(np.exp(rng.normal(0, NOISE_SIGMA)))
            oil, gas, water = round(oil, 3), round(gas, 3), round(water, 3)
            tef = _fmt(days)
            state, remarks = EFFECTIVE, ""
            if k in zero_at:
                oil = gas = water = 0.0
                tef = "0"
                truth_lists["zero_month_rows"].append((well_id, pk))
                if first_shutin:
                    truth_lists["effective_state_zero_rows"].append((well_id, pk))
                else:
                    state = STOPPED
                if auto_shutin:
                    remarks = AUTO_REMARK
                    truth_lists["auto_loaded_rows"].append((well_id, pk))
            if well_id == pick["negative"] and k == length // 2:
                gas = -12.5
                truth_lists["negative_gas_rows"].append((well_id, pk))
            if well_id == pick["tef_over"] and k == length // 3:
                tef = "45.5"
                truth_lists["tef_gt_days_rows"].append((well_id, pk))
            if well_id in (pick["tef_zero_a"], pick["tef_zero_b"]) and k == (10 if well_id == pick["tef_zero_a"] else 12):
                tef = "0"
                truth_lists["tef_zero_with_production_rows"].append((well_id, pk))
            company = operator
            if well_id in (pick["op_a"], pick["op_b"]) and k >= length // 2:
                company = other_operator
            ingress_year, ingress_month = (year, month + 1) if month < 12 else (year + 1, 1)
            ingress = (
                f"{ingress_year:04d}-{ingress_month:02d}-{int(rng.integers(8, 20)):02d} "
                f"{int(rng.integers(0, 24)):02d}:{int(rng.integers(0, 60)):02d}:{int(rng.integers(0, 60)):02d}"
                f".{int(rng.integers(0, 1_000_000)):06d}"
            )
            row = [""] * len(SOURCE_COLUMNS)
            row[_COL["idempresa"]] = company[0]
            row[_COL["anio"]] = str(year)
            row[_COL["mes"]] = str(month)
            row[_COL["idpozo"]] = str(well_id)
            row[_COL["prod_pet"]] = _fmt(oil)
            row[_COL["prod_gas"]] = _fmt(gas)
            row[_COL["prod_agua"]] = _fmt(water)
            for c in ("iny_agua", "iny_gas", "iny_co2", "iny_otro"):
                row[_COL[c]] = "0"
            row[_COL["tef"]] = tef
            row[_COL["tipoextraccion"]] = extraction
            row[_COL["tipoestado"]] = state
            row[_COL["tipopozo"]] = "Gasífero" if tight else "Petrolífero"
            row[_COL["observaciones"]] = remarks
            row[_COL["fechaingreso"]] = ingress
            row[_COL["rectificado"]] = "f"
            row[_COL["habilitado"]] = "t"
            row[_COL["idusuario"]] = company[2]
            row[_COL["empresa"]] = company[1]
            row[_COL["sigla"]] = well_code
            row[_COL["formprod"]] = formation[0]
            row[_COL["profundidad"]] = depth_text
            row[_COL["formacion"]] = formation[1]
            row[_COL["idareapermisoconcesion"]] = field_info[0]
            row[_COL["areapermisoconcesion"]] = field_info[1]
            row[_COL["idareayacimiento"]] = field_info[2]
            row[_COL["areayacimiento"]] = field_info[3]
            row[_COL["cuenca"]] = "NEUQUINA"
            row[_COL["provincia"]] = field_info[4]
            row[_COL["coordenadax"]] = f"{lon:.7f}"
            row[_COL["coordenaday"]] = f"{lat:.8f}"
            row[_COL["tipo_de_recurso"]] = "NO CONVENCIONAL"
            row[_COL["proyecto"]] = "GAS PLUS" if tight else "SHALE OIL"
            row[_COL["clasificacion"]] = "EXPLOTACION"
            row[_COL["subclasificacion"]] = "DESARROLLO"
            row[_COL["sub_tipo_recurso"]] = sub_type
            row[_COL["fecha_data"]] = f"{year:04d}-{month:02d}-{days:02d}"
            rows.append(row)

        start_year, start_month = _from_index(first_index + start)
        end_year, end_month = _from_index(first_index + end)
        wells[well_id] = WellTruth(
            well_id=well_id, well_code=well_code, kind=kind, sub_resource_type=sub_type,
            first_period_key=_key(start_year, start_month), last_period_key=_key(end_year, end_month),
            oil=CurveTruth(oil_curve), gas=CurveTruth(gas_curve),
        )

    n_rows_subset = len(rows)

    # Wells the pipeline must filter out: other basins and a conventional resource.
    outside = (("AUSTRAL", "NO CONVENCIONAL"), ("NEUQUINA", "CONVENCIONAL"), ("GOLFO SAN JORGE", "NO CONVENCIONAL"))
    out_ids: list[int] = []
    for j, (basin, resource) in enumerate(outside):
        well_id = 900_001 + j
        out_ids.append(well_id)
        for k in range(min(12, n_months)):
            year, month = _from_index(first_index + k)
            days = calendar.monthrange(year, month)[1]
            row = [""] * len(SOURCE_COLUMNS)
            row[_COL["idempresa"]] = "OTHER"
            row[_COL["anio"]], row[_COL["mes"]] = str(year), str(month)
            row[_COL["idpozo"]] = str(well_id)
            row[_COL["prod_pet"]] = _fmt(round(40 + 2 * k + 5 * j, 3))
            row[_COL["prod_gas"]] = _fmt(round(80 + 3 * k, 3))
            row[_COL["prod_agua"]] = "0"
            for c in ("iny_agua", "iny_gas", "iny_co2", "iny_otro"):
                row[_COL[c]] = "0"
            row[_COL["tef"]] = _fmt(days)
            row[_COL["tipoestado"]] = EFFECTIVE
            row[_COL["tipopozo"]] = "Petrolífero"
            row[_COL["fechaingreso"]] = f"{year:04d}-{month:02d}-02 10:00:00.000000"
            row[_COL["rectificado"]], row[_COL["habilitado"]] = "f", "t"
            row[_COL["empresa"]] = "OTHER OPERATOR S.A."
            row[_COL["sigla"]] = f"OUT.{j}-{well_id}"
            row[_COL["profundidad"]] = "2000"
            row[_COL["formacion"]] = "other"
            row[_COL["cuenca"]], row[_COL["provincia"]] = basin, "Santa Cruz"
            row[_COL["coordenadax"]], row[_COL["coordenaday"]] = "-69.0", "-49.5"
            row[_COL["tipo_de_recurso"]] = resource
            row[_COL["fecha_data"]] = f"{year:04d}-{month:02d}-{days:02d}"
            rows.append(row)

    _write_csv(path, [list(SOURCE_COLUMNS), *rows])
    return FixtureTruth(
        path=Path(path),
        n_wells=n_wells,
        n_rows=len(rows),
        n_rows_subset=n_rows_subset,
        first_period_key=_key(*first),
        last_period_key=_key(*last),
        wells=wells,
        out_of_scope_wells=out_ids,
        volume_ceiling_rows=[],
        swapped_coords_well=pick["swapped"] if pick["swapped"] is not None else -1,
        depth_invalid_wells=[w for w in (pick["depth_zero"], pick["depth_high"]) if w is not None],
        operator_change_wells=operator_changes,
        **truth_lists,
    )


def _write_csv(path: Path, table: list[list[str]], encoding: str = "utf-8-sig") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)  # `make-fixture data/quick/publication.csv` on a fresh clone
    with open(path, "w", encoding=encoding, newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(table)


def _read_table(path: Path) -> list[list[str]]:
    text = Path(path).read_bytes().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline="")))


def _is_in_scope(row: list[str]) -> bool:
    return row[_COL["cuenca"]] == "NEUQUINA" and row[_COL["tipo_de_recurso"]] == "NO CONVENCIONAL"


def make_malformed(base: Path, kind: str, out: Path) -> Path:
    """Write to `out` a copy of the valid file `base` damaged in the way `kind` says."""
    if kind not in MALFORMED_KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {', '.join(MALFORMED_KINDS)}")
    out = Path(out)

    if kind == "truncated":
        raw = Path(base).read_bytes()
        out.write_bytes(raw[: int(len(raw) * 0.6)])
        return out

    table = _read_table(base)
    header, data = table[0], table[1:]
    scoped = [i for i, r in enumerate(data) if _is_in_scope(r)]
    target = scoped[len(scoped) // 3]

    if kind == "missing_column":
        drop = header.index("prod_pet")
        table = [[v for j, v in enumerate(r) if j != drop] for r in table]
    elif kind == "renamed_column":
        header[header.index("prod_pet")] = "produccion_petroleo"
    elif kind == "non_numeric_well_id":
        data[target][_COL["idpozo"]] = "ABC"
    elif kind == "month_13":
        data[target][_COL["mes"]] = "13"
    elif kind == "duplicate_key":
        data.insert(target + 1, list(data[target]))
    elif kind == "bad_period_end":
        row = data[target]
        row[_COL["fecha_data"]] = f"{int(row[_COL['anio']]):04d}-{int(row[_COL['mes']]):02d}-01"
    elif kind == "regressed_last_period":
        last = max(int(r[_COL["anio"]]) * 100 + int(r[_COL["mes"]]) for r in data)
        data = [r for r in data if int(r[_COL["anio"]]) * 100 + int(r[_COL["mes"]]) != last]
    elif kind == "not_utf8":
        text = io.StringIO()
        csv.writer(text, lineterminator="\n").writerows([header, *data])
        out.write_bytes(text.getvalue().encode("cp1252"))
        return out

    if kind != "missing_column":
        table = [header, *data]
    _write_csv(out, table)
    return out


def main() -> None:  # pragma: no cover - thin command line wrapper
    import argparse

    parser = argparse.ArgumentParser(description="Write a synthetic publication.")
    parser.add_argument("output", type=Path)
    parser.add_argument("--wells", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    truth = make_fixture(args.output, n_wells=args.wells, seed=args.seed)
    print(f"{truth.n_rows} rows, {truth.n_wells} wells -> {truth.path}")


if __name__ == "__main__":  # pragma: no cover
    main()
