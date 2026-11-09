"""The two naive baselines, with values worked out by hand (AC10)."""

from __future__ import annotations

import numpy as np
import pytest

from oilgas.baselines import naive_last, naive_mean3

NAN = np.nan
DAYS = np.array([31.0, 28.0, 31.0])


def test_both_baselines_use_the_last_three_months_and_the_target_days() -> None:
    row = np.array([NAN, 10.0, 8.0, 6.0])
    assert naive_last(row, 3, DAYS).tolist() == [6 * 31, 6 * 28, 6 * 31]  # 6 m3/d repeated
    assert naive_mean3(row, 3, DAYS).tolist() == [8 * 31, 8 * 28, 8 * 31]  # mean(10, 8, 6) = 8


def test_the_window_is_the_origin_and_the_two_months_before_it() -> None:
    row = np.array([100.0, 10.0, 8.0, 6.0, 4.0])
    assert naive_last(row, 4, np.array([30.0])).tolist() == [4 * 30]
    assert naive_mean3(row, 4, np.array([30.0])).tolist() == [6 * 30]  # mean(8, 6, 4); the 100 and the 10 are out
    assert naive_mean3(row, 0, np.array([30.0])).tolist() == [100 * 30]  # an origin at the start has one month


def test_a_month_in_zero_counts_as_zero() -> None:
    row = np.array([10.0, 8.0, 0.0])
    assert naive_last(row, 2, DAYS).tolist() == [0.0, 0.0, 0.0]
    assert naive_mean3(row, 2, DAYS).tolist() == [6 * 31, 6 * 28, 6 * 31]  # mean(10, 8, 0) = 6


def test_a_month_without_a_row_does_not_count_at_all() -> None:
    row = np.array([10.0, 8.0, NAN])
    assert naive_last(row, 2, DAYS).tolist() == [8 * 31, 8 * 28, 8 * 31]  # the last month that has a row
    assert naive_mean3(row, 2, DAYS).tolist() == [9 * 31, 9 * 28, 9 * 31]  # mean(10, 8), not mean(10, 8, 0)
    only_old = np.array([7.0, NAN, NAN])
    assert naive_last(only_old, 2, DAYS).tolist() == [7 * 31, 7 * 28, 7 * 31]


def test_a_window_without_any_row_gives_nan() -> None:
    row = np.array([5.0, NAN, NAN, NAN])
    for baseline in (naive_last, naive_mean3):
        out = baseline(row, 3, DAYS)
        assert out.shape == (3,) and np.isnan(out).all()


def test_the_output_has_one_value_per_target_month() -> None:
    row = np.array([2.0, 2.0, 2.0])
    assert naive_last(row, 2, np.array([31.0] * 12)).shape == (12,)
    assert naive_mean3(row, 2, np.array([], dtype=float)).shape == (0,)


@pytest.mark.parametrize("baseline", [naive_last, naive_mean3])
def test_a_baseline_never_reads_after_the_origin(baseline) -> None:
    row = np.array([3.0, 5.0, 4.0, 6.0, 2.0, 9.0])
    changed = row.copy()
    changed[4:] = [1e6, 1e6]
    assert baseline(row, 3, DAYS).tolist() == baseline(changed, 3, DAYS).tolist()
