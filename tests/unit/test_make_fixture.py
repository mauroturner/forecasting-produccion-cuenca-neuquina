"""The fixture generator: what it promises is what the later units' tests rely on."""

from __future__ import annotations

import calendar
import csv
import io
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from oilgas.schema import SOURCE_COLUMNS
from tests.fixtures.make_fixture import (
    MALFORMED_KINDS,
    FixtureTruth,
    make_fixture,
    make_malformed,
    modified_hyperbolic_rate,
)


def read_rows(path: Path) -> list[dict[str, str]]:
    text = path.read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def period_key(row: dict[str, str]) -> int:
    return int(row["anio"]) * 100 + int(row["mes"])


@pytest.fixture(scope="module")
def rows(fixture_csv: Path) -> list[dict[str, str]]:
    return read_rows(fixture_csv)


def in_scope(row: dict[str, str]) -> bool:
    return row["cuenca"] == "NEUQUINA" and row["tipo_de_recurso"] == "NO CONVENCIONAL"


def test_file_has_bom_header_in_published_order_and_the_reported_row_count(
    fixture_csv: Path, fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    raw = fixture_csv.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw[3:].split(b"\n", 1)[0].decode("utf-8").split(",") == list(SOURCE_COLUMNS)
    assert len(rows) == fixture_truth.n_rows
    assert all(len(r) == 40 for r in rows)


def test_subset_has_sixty_wells_and_the_rest_is_out_of_scope(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    subset = [r for r in rows if in_scope(r)]
    assert len(subset) == fixture_truth.n_rows_subset
    assert len({r["idpozo"] for r in subset}) == fixture_truth.n_wells == 60
    outside = [r for r in rows if not in_scope(r)]
    assert outside and {int(r["idpozo"]) for r in outside} == set(fixture_truth.out_of_scope_wells)
    assert len(fixture_truth.out_of_scope_wells) == 3
    assert len({r["cuenca"] for r in outside} | {r["tipo_de_recurso"] for r in outside}) >= 3


def test_period_range_and_keys(fixture_truth: FixtureTruth, rows: list[dict[str, str]]) -> None:
    periods = [period_key(r) for r in rows]
    assert fixture_truth.first_period_key == min(periods) == 201801
    assert fixture_truth.last_period_key == max(periods) == 202412
    keys = Counter((r["idpozo"], r["anio"], r["mes"]) for r in rows)
    assert max(keys.values()) == 1
    for r in rows:
        year, month = int(r["anio"]), int(r["mes"])
        assert 1 <= month <= 12
        assert r["fecha_data"] == f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def test_volumes_follow_the_known_curves_with_lognormal_noise(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    residuals: list[float] = []
    for well_id, well in fixture_truth.wells.items():
        if well.kind != "regular":
            continue
        own = sorted((r for r in rows if int(r["idpozo"]) == well_id), key=period_key)
        for k, r in enumerate(own):
            if k == 0 or r["prod_pet"] == "" or float(r["prod_pet"]) <= 0:
                continue
            days = calendar.monthrange(int(r["anio"]), int(r["mes"]))[1]
            truth = float(modified_hyperbolic_rate(np.array([k - 1.0]), **well.oil.params)[0])
            residuals.append(np.log(float(r["prod_pet"]) / days) - np.log(truth))
    assert len(residuals) > 1000
    assert abs(float(np.mean(residuals))) < 0.02
    assert 0.08 < float(np.std(residuals)) < 0.12  # sigma = 0.1


def test_the_first_month_is_a_partial_ramp_so_the_peak_is_the_second(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    well_id, well = next((i, w) for i, w in fixture_truth.wells.items() if w.kind == "regular")
    own = sorted((r for r in rows if int(r["idpozo"]) == well_id), key=period_key)
    first_days = calendar.monthrange(int(own[0]["anio"]), int(own[0]["mes"]))[1]
    assert float(own[0]["prod_pet"]) / first_days < 0.8 * well.oil.params["qi"]


def test_quality_cases_are_where_the_truth_says(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    by_key = {(int(r["idpozo"]), period_key(r)): r for r in rows}
    negatives = [k for k, r in by_key.items() if r["prod_gas"] and float(r["prod_gas"]) < 0]
    assert negatives == fixture_truth.negative_gas_rows and len(negatives) == 1
    days_over = [
        k for k, r in by_key.items()
        if r["tef"] and float(r["tef"]) > calendar.monthrange(int(r["anio"]), int(r["mes"]))[1]
    ]
    assert days_over == fixture_truth.tef_gt_days_rows and len(days_over) == 1
    tef_zero = sorted(
        k for k, r in by_key.items()
        if r["tef"] and float(r["tef"]) == 0 and (float(r["prod_pet"]) > 0 or float(r["prod_gas"]) > 0)
    )
    assert tef_zero == sorted(fixture_truth.tef_zero_with_production_rows) and len(tef_zero) == 2
    assert fixture_truth.volume_ceiling_rows == []


def test_swapped_coordinates_and_invalid_depths(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    swapped = {
        int(r["idpozo"]) for r in rows
        if in_scope(r) and not (-71.5 <= float(r["coordenadax"]) <= -66.0)
    }
    assert swapped == {fixture_truth.swapped_coords_well}
    bad_depth = {
        int(r["idpozo"]) for r in rows if in_scope(r) and not (1 <= float(r["profundidad"]) <= 8000)
    }
    assert bad_depth == set(fixture_truth.depth_invalid_wells) and len(bad_depth) == 2


def test_fixed_attributes_do_not_change_but_operators_do_for_two_wells(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    fixed = ("sigla", "formacion", "areayacimiento", "provincia", "profundidad", "coordenadax", "sub_tipo_recurso")
    changed_operator = set()
    for well_id in fixture_truth.wells:
        own = [r for r in rows if int(r["idpozo"]) == well_id]
        for column in fixed:
            assert len({r[column] for r in own}) == 1, (well_id, column)
        if len({r["idempresa"] for r in own}) > 1:
            changed_operator.add(well_id)
    assert changed_operator == set(fixture_truth.operator_change_wells) and len(changed_operator) == 2
    assert {r["sub_tipo_recurso"] for r in rows if in_scope(r)} == {"SHALE", "TIGHT"}


def test_zero_months_missing_months_and_young_wells(
    fixture_truth: FixtureTruth, rows: list[dict[str, str]]
) -> None:
    by_key = {(int(r["idpozo"]), period_key(r)): r for r in rows}
    assert fixture_truth.zero_month_rows
    for key in fixture_truth.zero_month_rows:
        r = by_key[key]
        assert float(r["prod_pet"]) == 0 and float(r["prod_gas"]) == 0
    assert fixture_truth.missing_month_rows
    for key in fixture_truth.missing_month_rows:
        assert key not in by_key
    young = [i for i, w in fixture_truth.wells.items() if w.kind == "young"]
    assert len(young) >= 4
    for well_id in young:
        own = [period_key(r) for r in rows if int(r["idpozo"]) == well_id]
        assert len(own) <= 5 and max(own) == fixture_truth.last_period_key
    stopped = [i for i, w in fixture_truth.wells.items() if w.kind == "stopped"]
    assert stopped
    for well_id in stopped:
        assert max(period_key(r) for r in rows if int(r["idpozo"]) == well_id) < fixture_truth.last_period_key


def test_same_seed_gives_the_same_bytes_and_another_seed_does_not(tmp_path: Path) -> None:
    a = make_fixture(tmp_path / "a.csv", n_wells=12, seed=3).path.read_bytes()
    b = make_fixture(tmp_path / "b.csv", n_wells=12, seed=3).path.read_bytes()
    c = make_fixture(tmp_path / "c.csv", n_wells=12, seed=4).path.read_bytes()
    assert a == b
    assert a != c


def test_the_wells_argument_and_the_period_arguments_are_honoured(tmp_path: Path) -> None:
    truth = make_fixture(tmp_path / "s.csv", n_wells=15, first=(2020, 6), last=(2023, 2), seed=1)
    assert truth.n_wells == 15
    assert (truth.first_period_key, truth.last_period_key) == (202006, 202302)
    periods = {period_key(r) for r in read_rows(truth.path)}
    assert min(periods) == 202006 and max(periods) == 202302


# --- malformed variants -------------------------------------------------------------------------


def test_every_kind_is_listed() -> None:
    assert set(MALFORMED_KINDS) == {
        "missing_column", "renamed_column", "non_numeric_well_id", "month_13", "duplicate_key",
        "bad_period_end", "truncated", "regressed_last_period", "not_utf8",
    }


def test_unknown_kind_is_rejected(fixture_csv: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nonsense"):
        make_malformed(fixture_csv, "nonsense", tmp_path / "x.csv")


def test_malformed_variants_leave_the_base_untouched(fixture_csv: Path, malformed) -> None:
    before = fixture_csv.read_bytes()
    for kind in MALFORMED_KINDS:
        malformed(kind)
    assert fixture_csv.read_bytes() == before


def test_missing_column(malformed) -> None:
    rows = read_rows(malformed("missing_column"))
    assert "prod_pet" not in rows[0] and len(rows[0]) == 39


def test_renamed_column(malformed) -> None:
    rows = read_rows(malformed("renamed_column"))
    assert "prod_pet" not in rows[0] and "produccion_petroleo" in rows[0] and len(rows[0]) == 40


def test_non_numeric_well_id(malformed) -> None:
    bad = [r for r in read_rows(malformed("non_numeric_well_id")) if not r["idpozo"].isdigit()]
    assert len(bad) == 1 and in_scope(bad[0])


def test_month_13(malformed) -> None:
    bad = [r for r in read_rows(malformed("month_13")) if r["mes"] == "13"]
    assert len(bad) == 1 and in_scope(bad[0])


def test_duplicate_key(malformed, fixture_truth: FixtureTruth) -> None:
    rows = read_rows(malformed("duplicate_key"))
    keys = Counter((r["idpozo"], r["anio"], r["mes"]) for r in rows)
    assert len(rows) == fixture_truth.n_rows + 1
    assert [k for k, n in keys.items() if n == 2] and max(keys.values()) == 2
    duplicated = next(k for k, n in keys.items() if n == 2)
    assert in_scope(next(r for r in rows if (r["idpozo"], r["anio"], r["mes"]) == duplicated))


def test_bad_period_end(malformed) -> None:
    bad = [
        r for r in read_rows(malformed("bad_period_end"))
        if r["fecha_data"] != f"{int(r['anio']):04d}-{int(r['mes']):02d}-{calendar.monthrange(int(r['anio']), int(r['mes']))[1]:02d}"
    ]
    assert len(bad) == 1 and in_scope(bad[0])


def test_truncated(malformed, fixture_csv: Path, fixture_truth: FixtureTruth) -> None:
    path = malformed("truncated")
    assert path.stat().st_size < 0.7 * fixture_csv.stat().st_size
    assert len(read_rows(path)) < 0.99 * fixture_truth.n_rows


def test_regressed_last_period(malformed, fixture_truth: FixtureTruth) -> None:
    rows = read_rows(malformed("regressed_last_period"))
    assert max(period_key(r) for r in rows) < fixture_truth.last_period_key
    assert len(rows) < fixture_truth.n_rows


def test_not_utf8(malformed, fixture_csv: Path) -> None:
    raw = malformed("not_utf8").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert raw.decode("cp1252") == fixture_csv.read_bytes().decode("utf-8-sig")
