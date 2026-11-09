"""Data contract validation (RF03, RF04, AC03): each malformed fixture trips its blocking rule."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.schema import USED_COLUMNS
from oilgas.validate import (
    PreviousLoad,
    Severity,
    ValidationReport,
    validate_file,
)
from tests.fixtures.make_fixture import FixtureTruth

TODAY = date(2025, 1, 15)
CFG = load_config()


def run(path: Path, previous: PreviousLoad | None = None, today: date = TODAY, run_key: str = "r1"):
    return validate_file(path, CFG, previous, run_key, today)


def results(report: ValidationReport) -> dict:
    return {r.rule_id: r for r in report.results}


def failed_blocking(report: ValidationReport) -> set[str]:
    return {r.rule_id for r in report.results if r.severity is Severity.BLOCKING and not r.passed}


def previous_from(frame: pd.DataFrame, report: ValidationReport) -> PreviousLoad:
    totals = frame.groupby("period_key", as_index=False).agg(
        oil_m3=("oil_m3", "sum"), gas_thousand_m3=("gas_thousand_m3", "sum"), rows=("well_id", "size")
    )
    return PreviousLoad(report.rows_subset, report.wells_subset, report.last_period_key, totals)


@pytest.fixture(scope="module")
def valid(fixture_csv: Path):
    report, frame = run(fixture_csv)
    return report, frame


# --- the valid file -------------------------------------------------------------------------------


def test_the_valid_fixture_has_no_blocking_failures(valid, fixture_truth: FixtureTruth) -> None:
    report, frame = valid
    assert not report.blocking_failed
    assert failed_blocking(report) == set()
    assert frame is not None
    assert report.run_key == "r1"
    assert report.rows_file == fixture_truth.n_rows
    assert report.rows_subset == fixture_truth.n_rows_subset == len(frame)
    assert report.wells_subset == fixture_truth.n_wells
    assert (report.first_period_key, report.last_period_key) == (201801, 202412)


def test_every_rule_of_the_plan_is_reported_in_order(valid) -> None:
    report, _ = valid
    ids = [r.rule_id for r in report.results]
    assert ids == [f"V{n:02d}" for n in range(1, 21)] + ["I01", "I02", "I03"]
    severities = {r.rule_id: r.severity for r in report.results}
    assert all(severities[f"V{n:02d}"] is Severity.BLOCKING for n in range(1, 11))
    assert all(severities[f"V{n:02d}"] is Severity.WARNING for n in range(11, 21))
    assert all(severities[i] is Severity.INFO for i in ("I01", "I02", "I03"))
    assert all(r.name_es for r in report.results)


def test_the_source_hash_is_the_files(valid, fixture_csv: Path) -> None:
    import hashlib

    assert valid[0].source_sha256 == hashlib.sha256(fixture_csv.read_bytes()).hexdigest()


def test_the_validated_frame_is_the_scoped_subset_with_english_names_and_types(valid, fixture_truth) -> None:
    _, frame = valid
    english = [name for name, _ in USED_COLUMNS.values()]
    assert list(frame.columns) == [*english, "period_key", "period_index"]
    assert set(frame["basin"]) == {"NEUQUINA"} and set(frame["resource_type"]) == {"NO CONVENCIONAL"}
    assert set(frame["well_id"]) == set(fixture_truth.wells)
    for column in ("year", "month", "well_id", "period_key", "period_index"):
        assert str(frame[column].dtype) == "int64", column
    for column in ("oil_m3", "gas_thousand_m3", "water_m3", "effective_days", "depth_m", "lon", "lat"):
        assert str(frame[column].dtype) == "float64", column
    assert (frame["period_key"] == frame["year"] * 100 + frame["month"]).all()
    assert (frame["period_index"] == frame["year"] * 12 + frame["month"] - 1).all()
    assert str(frame["period_end"].dtype).startswith("datetime64")
    assert str(frame["loaded_at"].dtype).startswith("datetime64")
    assert set(frame["is_rectified"]) == {False} and set(frame["is_enabled"]) == {True}


def test_values_stay_raw_in_the_validated_frame(valid, fixture_truth) -> None:
    _, frame = valid
    well_id, period = fixture_truth.negative_gas_rows[0]
    row = frame[(frame["well_id"] == well_id) & (frame["period_key"] == period)].iloc[0]
    assert row["gas_thousand_m3"] == -12.5  # corrected in SQL, not here
    well_id, period = fixture_truth.tef_gt_days_rows[0]
    row = frame[(frame["well_id"] == well_id) & (frame["period_key"] == period)].iloc[0]
    assert row["effective_days"] == 45.5


def test_loading_the_same_publication_again_passes_every_comparison(valid, fixture_csv: Path) -> None:
    report, frame = valid
    again, frame2 = run(fixture_csv, previous_from(frame, report), run_key="r2")
    assert not again.blocking_failed and frame2 is not None
    for rule in ("V09", "V10", "V20"):
        assert results(again)[rule].passed, rule


# --- malformed files give their blocking rule (AC03) ----------------------------------------------


@pytest.mark.parametrize(
    ("kind", "rule"),
    [
        ("missing_column", "V02"),
        ("renamed_column", "V02"),
        ("non_numeric_well_id", "V03"),
        ("month_13", "V04"),
        ("duplicate_key", "V06"),
        ("bad_period_end", "V05"),
        ("not_utf8", "V01"),
    ],
)
def test_each_malformed_file_trips_its_rule(malformed, kind: str, rule: str) -> None:
    report, frame = run(malformed(kind))
    assert rule in failed_blocking(report)
    assert report.blocking_failed
    assert frame is None


@pytest.mark.parametrize(("kind", "rule"), [("truncated", "V09"), ("regressed_last_period", "V10")])
def test_files_that_regress_trip_their_rule_against_the_previous_load(malformed, valid, kind: str, rule: str) -> None:
    report, frame = valid
    damaged, damaged_frame = run(malformed(kind), previous_from(frame, report))
    assert rule in failed_blocking(damaged)
    assert damaged_frame is None


def test_a_valid_file_gives_zero_blocking_rules_while_every_malformed_one_gives_at_least_one(
    fixture_csv: Path, malformed, valid
) -> None:
    report, frame = valid
    previous = previous_from(frame, report)
    assert failed_blocking(run(fixture_csv, previous)[0]) == set()
    from tests.fixtures.make_fixture import MALFORMED_KINDS

    for kind in MALFORMED_KINDS:
        assert failed_blocking(run(malformed(kind), previous)[0]), kind


def test_a_renamed_column_is_also_reported_as_an_unknown_one(malformed) -> None:
    report, _ = run(malformed("renamed_column"))
    v19 = results(report)["V19"]
    assert not v19.passed and v19.examples == [{"column": "produccion_petroleo"}]
    v02 = results(report)["V02"]
    assert v02.examples == [{"column": "prod_pet"}]


def test_rules_that_cannot_be_evaluated_are_listed_not_invented(malformed) -> None:
    report, frame = run(malformed("not_utf8"))
    assert [r.rule_id for r in report.results] == ["V01"]
    assert "V03" in report.not_evaluated and "V01" not in report.not_evaluated
    assert report.rows_file == 0 and frame is None
    report, _ = run(malformed("missing_column"))
    assert {"V01", "V02", "V19"} <= {r.rule_id for r in report.results}
    assert "V03" in report.not_evaluated


def test_an_empty_file_is_not_utf8_csv(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    report, frame = run(empty)
    assert "V01" in failed_blocking(report) and frame is None
