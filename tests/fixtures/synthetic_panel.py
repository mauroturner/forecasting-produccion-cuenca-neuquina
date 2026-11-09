"""Synthetic series panels with known curves, built without a warehouse (for the model tests)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd

from oilgas.series import SeriesPanel, assemble_panel, days_in_months
from tests.fixtures.make_fixture import D_LIM, modified_hyperbolic_rate

FIRST_INDEX = 2018 * 12  # 2018-01


def synthetic_panel(
    n_wells: int = 12,
    n_months: int = 48,
    seed: int = 0,
    sigma: float = 0.1,
    young_wells: int = 2,
    with_awkward_cases: bool = True,
) -> SeriesPanel:
    """Wells with modified hyperbolic curves and lognormal noise.

    Most wells start in the first half of the period; the last `young_wells` start four months
    before the end. With `with_awkward_cases` one well has two months in zero, one has a missing
    month and one stops reporting four months before the end.
    """
    rng = np.random.default_rng(seed)
    period_index = np.arange(FIRST_INDEX, FIRST_INDEX + n_months)
    days = days_in_months(period_index)
    oil = np.full((n_wells, n_months), np.nan)
    gas = np.full((n_wells, n_months), np.nan)
    water = np.full((n_wells, n_months), np.nan)
    for i in range(n_wells):
        young = i >= n_wells - young_wells
        start = n_months - 4 if young else int(rng.integers(0, max(1, n_months // 2)))
        if with_awkward_cases and i < 2:
            start = int(rng.integers(0, max(1, n_months // 4)))
        end = n_months - 5 if (with_awkward_cases and i == 2) else n_months - 1
        t = np.arange(end - start + 1, dtype=float)
        qi = float(np.exp(rng.normal(np.log(200), 0.5)))
        di, b = float(rng.uniform(0.08, 0.3)), float(rng.uniform(0.4, 1.5))
        for volumes, scale in ((oil, 1.0), (gas, 2.0)):
            rate = scale * modified_hyperbolic_rate(t, qi, di, b, D_LIM) * np.exp(rng.normal(0, sigma, size=t.size))
            volumes[i, start : end + 1] = rate * days[start : end + 1]
        water[i, start : end + 1] = 0.5 * oil[i, start : end + 1]
        if with_awkward_cases and i == 0:  # an early shut-in and one in the last months
            for lo, hi in ((start + 8, start + 10), (n_months - 6, n_months - 4)):
                oil[i, lo:hi] = 0.0
                gas[i, lo:hi] = 0.0
        if with_awkward_cases and i == 1:  # an early missing month and one in the last months
            for col in (start + 10, n_months - 4):
                oil[i, col] = np.nan
                gas[i, col] = np.nan
    well_ids = 200_001 + np.arange(n_wells)
    attrs = pd.DataFrame(
        {
            "well_id": well_ids,
            "well_code": [f"SYN.{i}" for i in range(n_wells)],
            "province": "Neuquén",
            "formation_name": np.where(np.arange(n_wells) % 3 == 0, "lajas", "vaca muerta"),
            "sub_resource_type": np.where(np.arange(n_wells) % 3 == 0, "TIGHT", "SHALE"),
            "lon": -69.0 + 0.01 * np.arange(n_wells),
            "lat": -38.5 + 0.01 * np.arange(n_wells),
            "depth_m": 3000.0 + 10 * np.arange(n_wells),
        }
    )
    codes = {
        "operator": np.where(np.isnan(oil), -1, (np.arange(n_wells) % 2)[:, None]).astype(np.int16),
        "well_type": np.where(np.isnan(oil), -1, 0).astype(np.int16),
        "extraction_method": np.where(np.isnan(oil), -1, (np.arange(n_wells) % 3)[:, None]).astype(np.int16),
    }
    categories = {
        "operator": ("YPF", "VISTA"),
        "well_type": ("Petrolífero",),
        "extraction_method": ("Plunger Lift", "Gas Lift", "Surgencia Natural"),
    }
    return assemble_panel(well_ids, period_index, {"oil": oil, "gas": gas}, water, attrs, codes, categories)


def perturb_after(panel: SeriesPanel, origin_col: int, seed: int = 99, keep_gaps: bool = True) -> SeriesPanel:
    """A copy of the panel whose data after `origin_col` is scrambled.

    With `keep_gaps` the NaN pattern and the zeros stay (only positive values change), so the same
    (series, origin, horizon) pairs exist; without it a random share of the later cells is also
    emptied or set to zero.
    """
    rng = np.random.default_rng(seed)
    days = panel.days_in_month

    def scramble(volume: np.ndarray) -> np.ndarray:
        out = volume.copy()
        later = out[:, origin_col + 1 :]
        factor = np.exp(rng.normal(0, 1.0, size=later.shape))
        later = np.where(later > 0, later * factor, later)
        if not keep_gaps:
            drop = rng.random(later.shape) < 0.2
            later = np.where(drop, np.nan, later)
            later = np.where(rng.random(later.shape) < 0.1, 0.0, later)
        out[:, origin_col + 1 :] = later
        return out

    volume = {fluid: scramble(panel.volume[fluid]) for fluid in panel.volume}
    water = scramble(panel.water_rate * days[None, :]) / days[None, :]
    return dataclasses.replace(
        panel,
        volume=volume,
        rate={fluid: volume[fluid] / days[None, :] for fluid in volume},
        water_rate=water,
    )
