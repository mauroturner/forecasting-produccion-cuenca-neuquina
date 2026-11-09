"""The two naive baselines (RF08): repeat the last month, or the mean of the last three.

Both work on rates per calendar day over the window ``[origin - 2, origin]`` and turn the result into
volumes with the days of each target month. Months without a row are skipped; months in zero count.
If the whole window has no row the forecast is NaN (such a series is not active and is never evaluated).
"""

from __future__ import annotations

import numpy as np

WINDOW_MONTHS = 3


def _reported(rate_row: np.ndarray, upto: int) -> np.ndarray:
    window = rate_row[max(0, upto - WINDOW_MONTHS + 1) : upto + 1]
    return window[~np.isnan(window)]


def naive_last(rate_row: np.ndarray, upto: int, target_days: np.ndarray) -> np.ndarray:
    """Rate of the last month with a row in the window (it may be 0), times the target days; same for every horizon."""
    reported = _reported(rate_row, upto)
    rate = reported[-1] if reported.size else np.nan
    return rate * np.asarray(target_days, dtype=np.float64)


def naive_mean3(rate_row: np.ndarray, upto: int, target_days: np.ndarray) -> np.ndarray:
    """Mean rate of the months with a row in the window (zeros included), times the target days."""
    reported = _reported(rate_row, upto)
    rate = reported.mean() if reported.size else np.nan
    return rate * np.asarray(target_days, dtype=np.float64)
