"""The validation against the real publication of 2026-10-22: the figures profiled in requirements.md."""

from __future__ import annotations

from datetime import date

import pytest

from oilgas.config import load_config
from oilgas.validate import validate_file
from tests.conftest import REAL_CSV

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def outcome():
    return validate_file(REAL_CSV, load_config(), None, "real", date(2026, 11, 9))


def by_id(report, rule_id):
    return next(r for r in report.results if r.rule_id == rule_id)


def test_the_real_file_has_no_blocking_failures(outcome) -> None:
    report, frame = outcome
    assert [r.rule_id for r in report.results if r.severity.value == "blocking" and not r.passed] == []
    assert frame is not None and report.not_evaluated == ()


def test_subset_and_periods_match_the_profile(outcome) -> None:
    report, frame = outcome
    assert report.rows_file == 431_322
    assert report.rows_subset == len(frame) == 413_865
    assert report.wells_subset == 4_937
    assert (report.first_period_key, report.last_period_key) == (200601, 202609)


def test_warning_and_info_counts_match_the_profile(outcome) -> None:
    report, _ = outcome
    assert by_id(report, "V12").rows_affected == 2
    assert by_id(report, "V13").rows_affected == 70
    assert by_id(report, "V14").rows_affected == 384
    assert by_id(report, "V15").rows_affected == 0
    assert by_id(report, "V16").wells_affected == 1
    assert by_id(report, "V17").wells_affected == 172 + 4
    assert by_id(report, "V18").wells_affected == 0
    assert by_id(report, "V19").passed
    assert by_id(report, "I02").rows_affected == 7_421
    assert (by_id(report, "I03").rows_affected, by_id(report, "I03").wells_affected) == (7_420, 703)
