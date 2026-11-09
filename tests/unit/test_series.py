"""Series panel and the per-series rules: peak, post-peak segment, segments and age buckets (RF07)."""

from __future__ import annotations

import numpy as np
import pytest

from oilgas.series import (
    FLUIDS,
    SeriesPanel,
    age_bucket,
    build_panel,
    column_of,
    peak_column,
    post_peak_points,
    segment_at,
)
from oilgas.warehouse import apply_schema, connect

NAN = np.nan


def index_of(period_key: int) -> int:
    return (period_key // 100) * 12 + period_key % 100 - 1


# --- the panel --------------------------------------------------------------------------------------


def test_panel_covers_every_well_and_every_month(fixture_panel: SeriesPanel, fixture_truth) -> None:
    panel = fixture_panel
    assert panel.well_ids.tolist() == sorted(fixture_truth.wells)
    assert panel.period_index[0] == index_of(201801) and panel.period_index[-1] == index_of(202412)
    assert np.array_equal(np.diff(panel.period_index), np.ones(len(panel.period_index) - 1))  # contiguous
    shape = (60, 84)
    for fluid in FLUIDS:
        assert panel.volume[fluid].shape == shape and panel.rate[fluid].shape == shape
    assert panel.water_rate.shape == shape
    assert len(panel.attrs) == 60 and len(panel.days_in_month) == 84


def test_days_in_month_follow_the_calendar(fixture_panel: SeriesPanel) -> None:
    panel = fixture_panel
    by_period = dict(zip(panel.period_index.tolist(), panel.days_in_month.tolist(), strict=True))
    assert by_period[index_of(202002)] == 29 and by_period[index_of(202102)] == 28
    assert by_period[index_of(202004)] == 30 and by_period[index_of(202012)] == 31


def test_rate_is_volume_per_calendar_day(fixture_panel: SeriesPanel) -> None:
    panel = fixture_panel
    for fluid in FLUIDS:
        expected = panel.volume[fluid] / panel.days_in_month[None, :]
        assert np.array_equal(panel.rate[fluid], expected, equal_nan=True)


def test_zero_months_are_zero_and_months_without_a_row_are_nan(fixture_panel: SeriesPanel, fixture_truth) -> None:
    panel = fixture_panel
    assert fixture_truth.zero_month_rows and fixture_truth.missing_month_rows
    for well_id, period_key in fixture_truth.zero_month_rows:
        row, col = int(np.searchsorted(panel.well_ids, well_id)), column_of(panel, index_of(period_key))
        for fluid in FLUIDS:
            assert panel.volume[fluid][row, col] == 0.0 and panel.rate[fluid][row, col] == 0.0
        assert panel.water_rate[row, col] == 0.0
    for well_id, period_key in fixture_truth.missing_month_rows:
        row, col = int(np.searchsorted(panel.well_ids, well_id)), column_of(panel, index_of(period_key))
        for fluid in FLUIDS:
            assert np.isnan(panel.volume[fluid][row, col]) and np.isnan(panel.rate[fluid][row, col])
        assert np.isnan(panel.water_rate[row, col])


def test_the_corrected_negative_gas_volume_is_nan_but_its_oil_is_kept(fixture_panel: SeriesPanel, fixture_truth) -> None:
    panel = fixture_panel
    assert len(fixture_truth.negative_gas_rows) == 1
    well_id, period_key = fixture_truth.negative_gas_rows[0]
    row, col = int(np.searchsorted(panel.well_ids, well_id)), column_of(panel, index_of(period_key))
    assert np.isnan(panel.volume["gas"][row, col]) and np.isnan(panel.rate["gas"][row, col])
    assert panel.volume["oil"][row, col] > 0


def test_months_before_a_well_starts_and_after_it_stops_are_nan(fixture_panel: SeriesPanel, fixture_truth) -> None:
    panel = fixture_panel
    young = next(w for w in fixture_truth.wells.values() if w.kind == "young")
    row = int(np.searchsorted(panel.well_ids, young.well_id))
    first_col = column_of(panel, index_of(young.first_period_key))
    assert np.isnan(panel.rate["oil"][row, :first_col]).all()
    assert (panel.rate["oil"][row, first_col:] > 0).all()
    stopped = next(w for w in fixture_truth.wells.values() if w.kind == "stopped")
    row = int(np.searchsorted(panel.well_ids, stopped.well_id))
    last_col = column_of(panel, index_of(stopped.last_period_key))
    assert np.isnan(panel.rate["oil"][row, last_col + 1:]).all()


def test_attributes_are_aligned_with_the_wells_and_use_the_corrected_dimension(fixture_panel: SeriesPanel, fixture_truth) -> None:
    panel = fixture_panel
    attrs = panel.attrs
    assert attrs["well_id"].tolist() == panel.well_ids.tolist()
    for _, row in attrs.iterrows():
        assert row["sub_resource_type"] == fixture_truth.wells[int(row["well_id"])].sub_resource_type
    swapped = attrs[attrs["well_id"] == fixture_truth.swapped_coords_well].iloc[0]
    assert -71.5 <= swapped["lon"] <= -66.0 and -41.5 <= swapped["lat"] <= -34.5  # swapped back by dim_well
    invalid = attrs[attrs["well_id"].isin(fixture_truth.depth_invalid_wells)]
    assert len(invalid) == 2 and invalid["depth_m"].isna().all()
    for column in ("well_code", "formation_name", "province", "lon", "lat", "depth_m"):
        assert column in attrs.columns


def test_categories_that_change_by_month_are_coded_and_carry_the_last_known_value(fixture_panel: SeriesPanel, fixture_truth) -> None:
    panel = fixture_panel
    assert set(panel.period_codes) == {"operator", "well_type", "extraction_method"}
    assert set(panel.categories) == set(panel.period_codes)
    well_id = fixture_truth.operator_change_wells[0]
    row = int(np.searchsorted(panel.well_ids, well_id))
    truth = fixture_truth.wells[well_id]
    first_col, last_col = column_of(panel, index_of(truth.first_period_key)), column_of(panel, index_of(truth.last_period_key))
    codes = panel.period_codes["operator"][row]
    labels = panel.categories["operator"]
    assert codes[first_col] >= 0 and codes[last_col] >= 0 and codes[first_col] != codes[last_col]  # the operator changed
    assert labels[codes[first_col]] != labels[codes[last_col]]
    assert (codes[:first_col] == -1).all()  # nothing is known before the first report
    # A month without a row repeats the previous month's value (never a later one).
    gap_well, gap_period = fixture_truth.missing_month_rows[0]
    g_row, g_col = int(np.searchsorted(panel.well_ids, gap_well)), column_of(panel, index_of(gap_period))
    assert panel.period_codes["extraction_method"][g_row, g_col] == panel.period_codes["extraction_method"][g_row, g_col - 1] >= 0


def test_well_sample_is_a_fixed_subset(warehouse_conn, fixture_panel: SeriesPanel) -> None:
    sample = build_panel(warehouse_conn, well_sample=12, seed=3)
    again = build_panel(warehouse_conn, well_sample=12, seed=3)
    other = build_panel(warehouse_conn, well_sample=12, seed=4)
    assert len(sample.well_ids) == 12 and sample.rate["oil"].shape[0] == 12 and len(sample.attrs) == 12
    assert np.array_equal(sample.well_ids, again.well_ids) and np.array_equal(sample.rate["oil"], again.rate["oil"], equal_nan=True)
    assert not np.array_equal(sample.well_ids, other.well_ids)
    assert np.all(np.diff(sample.well_ids) > 0) and set(sample.well_ids) <= set(fixture_panel.well_ids)
    rows = np.searchsorted(fixture_panel.well_ids, sample.well_ids)
    assert np.array_equal(sample.rate["gas"], fixture_panel.rate["gas"][rows], equal_nan=True)
    assert len(build_panel(warehouse_conn, well_sample=1000).well_ids) == 60  # more than there are: all of them


def test_building_a_panel_from_an_empty_warehouse_fails(tmp_path) -> None:
    conn = connect(tmp_path / "empty.sqlite")
    apply_schema(conn)
    with pytest.raises(ValueError, match="no production"):
        build_panel(conn)


def test_column_of_maps_a_period_index_to_its_column(fixture_panel: SeriesPanel) -> None:
    panel = fixture_panel
    assert column_of(panel, int(panel.period_index[0])) == 0
    assert column_of(panel, int(panel.period_index[-1])) == 83
    assert column_of(panel, index_of(202007)) == 30
    for outside in (int(panel.period_index[0]) - 1, int(panel.period_index[-1]) + 1):
        with pytest.raises(ValueError, match="outside the panel"):
            column_of(panel, outside)


# --- peak, post-peak points, segments ---------------------------------------------------------------


def test_peak_is_the_first_maximum_of_the_positive_rates_up_to_the_origin() -> None:
    row = np.array([NAN, 5.0, 8.0, 8.0, 3.0, 0.0, 4.0])
    assert peak_column(row, 6) == 2  # a tie keeps the first
    assert peak_column(row, 1) == 1 and peak_column(row, 3) == 2
    assert peak_column(np.array([NAN, 0.0, 0.0]), 2) is None and peak_column(np.array([NAN, NAN]), 1) is None
    restimulated = np.array([10.0, 5.0, 3.0, 12.0, 6.0])
    assert peak_column(restimulated, 2) == 0 and peak_column(restimulated, 4) == 3  # a higher peak starts a new segment


def test_post_peak_points_skip_zero_and_missing_months_but_time_keeps_running() -> None:
    row = np.array([NAN, 5.0, 8.0, NAN, 6.0, 0.0, 4.0])
    t, rate = post_peak_points(row, 6)
    assert t.tolist() == [0.0, 2.0, 4.0] and rate.tolist() == [8.0, 6.0, 4.0]
    t, rate = post_peak_points(row, 2)
    assert t.tolist() == [0.0] and rate.tolist() == [8.0]
    t, rate = post_peak_points(np.array([NAN, 0.0]), 1)
    assert t.size == 0 and rate.size == 0


@pytest.mark.parametrize(
    ("upto", "expected"),
    [(4, "young"), (5, "eligible"), (7, "eligible")],  # 5, 6 and 8 points since the peak
)
def test_a_series_needs_six_points_since_the_peak_to_be_eligible(upto: int, expected: str) -> None:
    row = np.array([10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0])
    assert segment_at(row, upto, 6) == expected


def test_a_series_without_production_in_the_last_three_months_is_inactive() -> None:
    row = np.array([10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 0.0, 0.0, 0.0])
    assert segment_at(row, 8, 6) == "inactive"
    assert segment_at(row, 7, 6) == "eligible"  # cols 5, 6, 7 = 5, 0, 0: still active
    assert segment_at(np.full(5, NAN), 4, 6) == "inactive"
    assert segment_at(np.array([NAN, NAN, 4.0]), 2, 6) == "young"  # one point, but active
    assert segment_at(row, 8, 3) == "inactive"


def test_the_minimum_number_of_points_is_a_parameter() -> None:
    row = np.array([10.0, 9.0, 8.0, 7.0])
    assert segment_at(row, 3, 4) == "eligible" and segment_at(row, 3, 5) == "young"


def test_no_rule_looks_beyond_the_origin() -> None:
    rng = np.random.default_rng(1)
    row = rng.uniform(1, 20, size=30)
    row[[4, 9]] = NAN
    row[12] = 0.0
    for upto in (5, 14, 20):
        changed = row.copy()
        changed[upto + 1:] = 10_000.0
        assert peak_column(row, upto) == peak_column(changed, upto)
        for got, want in zip(post_peak_points(row, upto), post_peak_points(changed, upto), strict=True):
            assert np.array_equal(got, want)
        assert segment_at(row, upto, 6) == segment_at(changed, upto, 6)


@pytest.mark.parametrize(
    ("points", "bucket"),
    [(0, "young"), (5, "young"), (6, "06-11"), (11, "06-11"), (12, "12-23"), (23, "12-23"),
     (24, "24-59"), (59, "24-59"), (60, "60+"), (249, "60+")],
)
def test_age_buckets(points: int, bucket: str) -> None:
    assert age_bucket(points) == bucket
