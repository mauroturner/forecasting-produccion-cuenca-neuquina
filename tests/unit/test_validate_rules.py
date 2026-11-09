"""Each validation rule on its own: thresholds, counts, examples and the report files."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.schema import read_source_csv
from oilgas.validate import (
    PreviousLoad,
    RuleResult,
    Severity,
    ValidationError,
    ValidationReport,
    validate_file,
    write_report,
)
from tests.fixtures.make_fixture import FixtureTruth

TODAY = date(2025, 1, 15)
CFG = load_config()


def run(path: Path, previous: PreviousLoad | None = None, today: date = TODAY, run_key: str = "r1"):
    return validate_file(path, CFG, previous, run_key, today)


def rule(report: ValidationReport, rule_id: str) -> RuleResult:
    return next(r for r in report.results if r.rule_id == rule_id)


@pytest.fixture()
def edit(fixture_csv: Path, tmp_path: Path) -> Callable[[Callable[[pd.DataFrame], None]], Path]:
    """Apply `change(frame)` to the valid fixture read as text and write the result to a new file."""
    counter = iter(range(1000))

    def apply(change: Callable[[pd.DataFrame], None]) -> Path:
        frame = read_source_csv(fixture_csv)
        change(frame)
        out = tmp_path / f"edited{next(counter)}.csv"
        frame.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
        return out

    return apply


@pytest.fixture(scope="module")
def valid(fixture_csv: Path):
    return run(fixture_csv)


def scoped(frame: pd.DataFrame) -> pd.Series:
    return (frame["cuenca"] == "NEUQUINA") & (frame["tipo_de_recurso"] == "NO CONVENCIONAL")


# --- blocking rules -------------------------------------------------------------------------------


def test_v01_names_the_decoding_error(malformed) -> None:
    report, _ = run(malformed("not_utf8"))
    v01 = rule(report, "V01")
    assert not v01.passed and v01.severity is Severity.BLOCKING
    assert "utf-8" in v01.examples[0]["error"].lower()


def test_v02_lists_the_missing_columns(edit) -> None:
    path = edit(lambda f: f.drop(columns=["prod_pet", "prod_gas"], inplace=True))
    v02 = rule(run(path)[0], "V02")
    assert not v02.passed
    assert {e["column"] for e in v02.examples} == {"prod_pet", "prod_gas"}


def test_v02_ignores_the_unused_columns_and_their_order(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        frame.drop(columns=["iny_agua", "vida_util"], inplace=True)
        frame.insert(0, "fecha_data_copy", "x")

    path = edit(change)
    report, frame = run(path)
    assert rule(report, "V02").passed and frame is not None
    assert not rule(report, "V19").passed  # the added column is reported, not rejected
    assert "fecha_data_copy" not in frame.columns


@pytest.mark.parametrize("column", ["idpozo", "anio", "mes"])
@pytest.mark.parametrize("bad", ["", "ABC", "3.5"])
def test_v03_rejects_missing_and_non_integer_keys(edit, column: str, bad: str) -> None:
    def change(frame: pd.DataFrame) -> None:
        frame.loc[frame.index[scoped(frame)][10], column] = bad or None

    report, frame = run(edit(change))
    v03 = rule(report, "V03")
    assert not v03.passed and v03.rows_affected == 1 and frame is None


def test_v03_accepts_integers_written_with_a_decimal_point(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        frame["idpozo"] = frame["idpozo"] + ".0"

    report, frame = run(edit(change))
    assert rule(report, "V03").passed and frame is not None
    assert str(frame["well_id"].dtype) == "int64"


def test_v03_ignores_rows_outside_the_scope(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        frame.loc[frame.index[~scoped(frame)][0], "idpozo"] = "ABC"

    report, frame = run(edit(change))
    assert rule(report, "V03").passed and frame is not None


def test_v04_flags_months_outside_1_to_12_years_before_the_scope_and_future_periods(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        rows = frame.index[scoped(frame)]
        frame.loc[rows[0], "mes"] = "0"
        frame.loc[rows[1], "anio"] = "2005"
        frame.loc[rows[2], "anio"] = "2025"  # after 2025-01-15 once the month is 6
        frame.loc[rows[2], "mes"] = "6"

    report, _ = run(edit(change))
    v04 = rule(report, "V04")
    assert not v04.passed and v04.rows_affected == 3


def test_v04_a_period_after_today_fails(fixture_csv: Path, fixture_truth: FixtureTruth) -> None:
    report, frame = run(fixture_csv, today=date(2024, 6, 30))
    v04 = rule(report, "V04")
    assert not v04.passed and frame is None
    expected = len(pd.read_csv(fixture_csv, encoding="utf-8-sig", usecols=["anio", "mes", "cuenca", "tipo_de_recurso"]).query(
        "cuenca == 'NEUQUINA' and tipo_de_recurso == 'NO CONVENCIONAL' and (anio * 100 + mes) > 202406"
    ))
    assert v04.rows_affected == expected > 0
    assert rule(run(fixture_csv, today=date(2024, 12, 31))[0], "V04").passed


def test_v05_counts_rows_whose_period_end_is_not_the_last_day_or_not_a_date(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        rows = frame.index[scoped(frame)]
        frame.loc[rows[0], "fecha_data"] = "2018-01-30"
        frame.loc[rows[1], "fecha_data"] = "not a date"
        frame.loc[rows[2], "fecha_data"] = None

    v05 = rule(run(edit(change))[0], "V05")
    assert not v05.passed and v05.rows_affected == 3


def test_v05_knows_leap_years(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        row = frame.index[scoped(frame)][0]
        frame.loc[row, ["anio", "mes", "fecha_data"]] = ["2020", "2", "2020-02-29"]
        row = frame.index[scoped(frame)][1]
        frame.loc[row, ["anio", "mes", "fecha_data"]] = ["2019", "2", "2019-02-29"]

    v05 = rule(run(edit(change))[0], "V05")
    assert v05.rows_affected == 1 and v05.examples[0]["value"] == "2019-02-29"


def test_v06_counts_the_surplus_rows_and_gives_the_key(malformed) -> None:
    v06 = rule(run(malformed("duplicate_key"))[0], "V06")
    assert not v06.passed and v06.rows_affected == 1 and v06.wells_affected == 1
    assert set(v06.examples[0]) == {"well_id", "period_key"}


def test_v07_tolerates_up_to_a_tenth_of_a_percent_of_bad_volumes(edit) -> None:
    def few(frame: pd.DataFrame) -> None:
        frame.loc[frame.index[scoped(frame)][:2], "prod_pet"] = "abc"

    def many(frame: pd.DataFrame) -> None:
        frame.loc[frame.index[scoped(frame)][:20], "prod_gas"] = None

    ok_report, ok_frame = run(edit(few))
    v07 = rule(ok_report, "V07")
    assert v07.passed and v07.rows_affected == 2 and ok_frame is not None
    assert ok_frame["oil_m3"].isna().sum() == 2  # unconvertible values become missing
    bad_report, bad_frame = run(edit(many))
    assert not rule(bad_report, "V07").passed and rule(bad_report, "V07").rows_affected == 20 and bad_frame is None


def test_v08_fails_on_an_empty_subset(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        frame["cuenca"] = "AUSTRAL"

    report, frame = run(edit(change))
    assert not rule(report, "V08").passed and frame is None
    assert (report.rows_subset, report.wells_subset) == (0, 0)
    assert report.rows_file > 0


def test_v09_thresholds_on_rows_and_wells(valid, fixture_csv: Path) -> None:
    report, frame = valid
    totals = frame.groupby("period_key", as_index=False).agg(oil_m3=("oil_m3", "sum"), gas_thousand_m3=("gas_thousand_m3", "sum"))
    rows, wells = report.rows_subset, report.wells_subset

    def previous(r: float, w: float) -> PreviousLoad:
        return PreviousLoad(int(r), int(w), report.last_period_key, totals)

    ok = rule(run(fixture_csv, previous(rows / 0.995, wells))[0], "V09")
    assert ok.passed
    too_many_rows = rule(run(fixture_csv, previous(rows / 0.98, wells))[0], "V09")
    assert not too_many_rows.passed and too_many_rows.rows_affected > 0 and too_many_rows.wells_affected == 0
    too_many_wells = rule(run(fixture_csv, previous(rows, wells / 0.9))[0], "V09")
    assert not too_many_wells.passed and too_many_wells.wells_affected > 0
    assert rule(run(fixture_csv, None)[0], "V09").passed  # first load: nothing to compare


def test_v10_compares_the_last_period_with_the_previous_load(valid, fixture_csv: Path) -> None:
    report, frame = valid
    totals = frame.groupby("period_key", as_index=False).agg(oil_m3=("oil_m3", "sum"), gas_thousand_m3=("gas_thousand_m3", "sum"))
    same = PreviousLoad(report.rows_subset, report.wells_subset, 202412, totals)
    later = PreviousLoad(report.rows_subset, report.wells_subset, 202501, totals)
    assert rule(run(fixture_csv, same)[0], "V10").passed
    v10 = rule(run(fixture_csv, later)[0], "V10")
    assert not v10.passed
    assert v10.examples == [{"last_period_key": 202412, "previous_last_period_key": 202501}]


# --- warnings and the SQL corrections they must match ---------------------------------------------


def test_corrections_counts_match_the_fixture_truth(valid, fixture_truth: FixtureTruth) -> None:
    report, _ = valid
    v12, v13, v14, v15 = (rule(report, r) for r in ("V12", "V13", "V14", "V15"))
    assert (v12.rows_affected, v12.wells_affected, v12.passed) == (1, 1, False)
    assert v12.examples == [{"well_id": fixture_truth.negative_gas_rows[0][0], "period_key": fixture_truth.negative_gas_rows[0][1], "value": -12.5}]
    assert (v13.rows_affected, v13.wells_affected) == (1, 1)
    assert (v13.examples[0]["well_id"], v13.examples[0]["period_key"]) == fixture_truth.tef_gt_days_rows[0]
    assert v13.examples[0]["value"] == 45.5
    assert (v14.rows_affected, v14.wells_affected) == (2, 2)
    assert sorted((e["well_id"], e["period_key"]) for e in v14.examples) == sorted(fixture_truth.tef_zero_with_production_rows)
    assert (v15.rows_affected, v15.passed, v15.examples) == (0, True, [])
    assert all(r.severity is Severity.WARNING for r in (v12, v13, v14, v15))


def test_v12_counts_any_negative_volume(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        rows = frame.index[scoped(frame)]
        frame.loc[rows[3], "prod_pet"] = "-1"
        frame.loc[rows[4], "prod_agua"] = "-2"
        frame.loc[rows[5], ["prod_pet", "prod_gas"]] = ["-3", "-4"]  # one row, two negatives

    v12 = rule(run(edit(change))[0], "V12")
    assert v12.rows_affected == 4  # the 3 edited rows plus the fixture's negative gas


def test_v13_does_not_flag_a_month_that_has_that_many_days(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        row = frame.index[scoped(frame)][0]
        frame.loc[row, ["anio", "mes", "fecha_data", "tef"]] = ["2020", "2", "2020-02-29", "29"]
        row = frame.index[scoped(frame)][1]
        frame.loc[row, ["anio", "mes", "fecha_data", "tef"]] = ["2019", "2", "2019-02-28", "29"]

    assert rule(run(edit(change))[0], "V13").rows_affected == 2  # the fixture's 45.5 and the 29 in February 2019


def test_v15_flags_volumes_over_the_ceilings(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        rows = frame.index[scoped(frame)]
        frame.loc[rows[0], "prod_pet"] = "30001"
        frame.loc[rows[-1], "prod_gas"] = "60001"  # the last row belongs to another well
        frame.loc[rows[2], "prod_pet"] = "30000"  # at the ceiling: fine

    v15 = rule(run(edit(change))[0], "V15")
    assert not v15.passed and v15.rows_affected == 2 and v15.wells_affected == 2


def test_v16_swapped_and_outside_coordinates_are_counted_by_well(valid, fixture_truth: FixtureTruth, edit) -> None:
    report, frame = valid
    v16 = rule(report, "V16")
    assert (v16.wells_affected, v16.passed) == (1, False)
    swapped_rows = int((frame["well_id"] == fixture_truth.swapped_coords_well).sum())
    assert v16.rows_affected == swapped_rows
    assert v16.examples[0]["well_id"] == fixture_truth.swapped_coords_well

    def change(f: pd.DataFrame) -> None:
        well = str(sorted(fixture_truth.wells)[1])
        f.loc[f["idpozo"] == well, "coordenadax"] = "-10.0"

    assert rule(run(edit(change))[0], "V16").wells_affected == 2


def test_v17_counts_wells_with_a_depth_outside_the_range(valid, fixture_truth: FixtureTruth, edit) -> None:
    report, _ = valid
    v17 = rule(report, "V17")
    assert v17.wells_affected == 2 and not v17.passed
    assert {e["well_id"] for e in v17.examples} == set(fixture_truth.depth_invalid_wells)

    def change(f: pd.DataFrame) -> None:
        f.loc[f["idpozo"] == str(sorted(fixture_truth.wells)[2]), "profundidad"] = "8000"  # at the limit: fine

    assert rule(run(edit(change))[0], "V17").wells_affected == 2


def test_v18_flags_a_fixed_attribute_that_changes_inside_a_well(valid, fixture_truth: FixtureTruth, edit) -> None:
    assert rule(valid[0], "V18").passed

    def change(f: pd.DataFrame) -> None:
        well = str(sorted(fixture_truth.wells)[4])
        row = f.index[f["idpozo"] == well][0]
        f.loc[row, "provincia"] = "Mendoza X"

    v18 = rule(run(edit(change))[0], "V18")
    assert not v18.passed and v18.wells_affected == 1 and v18.rows_affected > 1
    assert v18.examples[0]["well_id"] == sorted(fixture_truth.wells)[4]


def test_v18_does_not_count_a_change_of_operator(valid) -> None:
    assert rule(valid[0], "V18").wells_affected == 0  # the fixture has two wells that change operator


def test_v11_flags_a_last_period_with_far_fewer_rows(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        last = frame[scoped(frame) & (frame["anio"] == "2024") & (frame["mes"] == "12")]
        frame.drop(index=last.index[: int(len(last) * 0.3)], inplace=True)

    report, frame = run(edit(change))
    v11 = rule(report, "V11")
    assert not v11.passed and v11.rows_affected > 0
    assert frame is not None  # a warning does not reject the file
    assert not report.blocking_failed


def test_v11_passes_on_the_valid_fixture(valid) -> None:
    assert rule(valid[0], "V11").passed


def test_v19_lists_every_new_column(edit) -> None:
    def change(frame: pd.DataFrame) -> None:
        frame["nueva_a"] = "1"
        frame["nueva_b"] = "2"

    v19 = rule(run(edit(change))[0], "V19")
    assert not v19.passed and {e["column"] for e in v19.examples} == {"nueva_a", "nueva_b"}
    assert rule(run(edit(lambda f: None))[0], "V19").passed


def test_v20_flags_old_periods_whose_total_changed_more_than_one_percent(valid, fixture_csv: Path, edit) -> None:
    report, frame = valid
    totals = frame.groupby("period_key", as_index=False).agg(oil_m3=("oil_m3", "sum"), gas_thousand_m3=("gas_thousand_m3", "sum"))

    def previous_with(changes: dict[int, float]) -> PreviousLoad:
        t = totals.copy()
        for period, factor in changes.items():
            t.loc[t["period_key"] == period, ["oil_m3", "gas_thousand_m3"]] *= factor
        return PreviousLoad(report.rows_subset, report.wells_subset, report.last_period_key, t)

    # 2024-12 is the last period: 202410 is 2 months old, 202408 is 4 months old (> 3)
    assert rule(run(fixture_csv, previous_with({202410: 1.5}))[0], "V20").passed  # too recent to count
    assert rule(run(fixture_csv, previous_with({202408: 1.005}))[0], "V20").passed  # inside the 1 % tolerance
    v20 = rule(run(fixture_csv, previous_with({202408: 1.05, 202201: 0.9}))[0], "V20")
    assert not v20.passed
    assert {e["period_key"] for e in v20.examples} == {202408, 202201}
    assert v20.rows_affected == int(frame["period_key"].isin([202408, 202201]).sum())
    assert v20.severity is Severity.WARNING
    extra = pd.DataFrame({"period_key": [201712], "oil_m3": [100.0], "gas_thousand_m3": [100.0]})  # absent from the new file
    vanished = PreviousLoad(report.rows_subset, report.wells_subset, report.last_period_key, pd.concat([totals, extra]))
    v20 = rule(run(fixture_csv, vanished)[0], "V20")
    assert not v20.passed and [e["period_key"] for e in v20.examples] == [201712]
    assert rule(run(fixture_csv, None)[0], "V20").passed


# --- informational rules --------------------------------------------------------------------------


def test_informational_counts_match_the_fixture_truth(valid, fixture_truth: FixtureTruth) -> None:
    report, _ = valid
    i01, i02, i03 = (rule(report, r) for r in ("I01", "I02", "I03"))
    assert all(r.severity is Severity.INFO and r.passed for r in (i01, i02, i03))
    assert i01.rows_affected == len(fixture_truth.effective_state_zero_rows) > 0
    assert i02.rows_affected == len(fixture_truth.auto_loaded_rows) > 0
    assert i03.rows_affected == len(fixture_truth.missing_month_rows) > 0
    assert i03.wells_affected == len({w for w, _ in fixture_truth.missing_month_rows})
    assert sorted((e["well_id"], e["period_key"]) for e in i01.examples) == sorted(fixture_truth.effective_state_zero_rows)


# --- the report files -----------------------------------------------------------------------------


def test_write_report_writes_latest_and_a_history_copy(valid, tmp_path: Path) -> None:
    report, _ = valid
    json_path, md_path = write_report(report, tmp_path / "validation")
    assert (json_path.name, md_path.name) == ("latest.json", "latest.md")
    assert (tmp_path / "validation" / "history" / "r1.json").read_bytes() == json_path.read_bytes()
    assert (tmp_path / "validation" / "history" / "r1.md").read_bytes() == md_path.read_bytes()
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["run_key"] == "r1" and document["blocking_failed"] is False
    assert document["rows_subset"] == report.rows_subset and document["wells_subset"] == 60
    assert document["source_sha256"] == report.source_sha256
    assert [r["rule_id"] for r in document["results"]] == [r.rule_id for r in report.results]
    v12 = next(r for r in document["results"] if r["rule_id"] == "V12")
    assert v12["status"] == "advierte" and v12["severity"] == "advertencia" and v12["rows_affected"] == 1
    assert v12["examples"][0]["value"] == -12.5
    v01 = next(r for r in document["results"] if r["rule_id"] == "V01")
    assert (v01["status"], v01["severity"]) == ("pasa", "bloqueante")
    i01 = next(r for r in document["results"] if r["rule_id"] == "I01")
    assert (i01["status"], i01["severity"]) == ("pasa", "informativa")


def test_the_markdown_report_is_a_spanish_table_with_examples_of_the_failures(malformed, tmp_path: Path) -> None:
    report, _ = run(malformed("month_13"), run_key="r9")
    _, md_path = write_report(report, tmp_path)
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("# Reporte de validación")
    assert "r9" in text and "| V04 |" in text and "falla" in text and "bloqueante" in text
    assert "## Ejemplos" in text and "V04" in text.split("## Ejemplos")[1]
    assert "Rechazado" in text  # the verdict line


def test_the_markdown_report_says_which_rules_were_not_evaluated(malformed, tmp_path: Path) -> None:
    report, _ = run(malformed("not_utf8"))
    _, md_path = write_report(report, tmp_path)
    assert "No evaluadas" in md_path.read_text(encoding="utf-8")


def test_a_second_report_replaces_latest_but_keeps_history(valid, malformed, tmp_path: Path) -> None:
    write_report(valid[0], tmp_path)
    second, _ = run(malformed("month_13"), run_key="r2")
    json_path, _ = write_report(second, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["run_key"] == "r2"
    assert (tmp_path / "history" / "r1.json").exists() and (tmp_path / "history" / "r2.json").exists()


def test_the_report_files_are_reproducible(valid, tmp_path: Path) -> None:
    first = write_report(valid[0], tmp_path / "a")
    second = write_report(valid[0], tmp_path / "b")
    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()


def test_validation_error_is_a_runtime_error() -> None:
    assert issubclass(ValidationError, RuntimeError)


def test_i02_counts_the_published_variants_of_the_automatic_remark(valid, edit) -> None:
    baseline = rule(valid[0], "I02").rows_affected

    def change(frame: pd.DataFrame) -> None:
        rows = frame.index[scoped(frame)]
        frame.loc[rows[0], "observaciones"] = "Cargado autom?camente como [Sin movimientos]"  # mangled accent, as published
        frame.loc[rows[1], "observaciones"] = "Sin movimientos"  # not the marker: does not count

    assert rule(run(edit(change))[0], "I02").rows_affected == baseline + 1


def test_example_identifiers_are_integers(valid, tmp_path: Path) -> None:
    report, _ = valid
    for r in report.results:
        for example in r.examples:
            for name in ("well_id", "period_key", "missing_months"):
                if name in example:
                    assert type(example[name]) is int, (r.rule_id, example)
    text = write_report(report, tmp_path)[0].read_text(encoding="utf-8")
    assert '"well_id": 1000' in text and ".0," not in text.split('"V12"')[1].split('"V13"')[0]
