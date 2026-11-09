"""Fracture features for the ablation (RF21, D15): reading the file, values by hand and no leakage (end date <= origin)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oilgas.config import load_config
from oilgas.features import FEATURE_COLUMNS, features_at, training_examples
from oilgas.fracture import FRACTURE_FEATURES, REQUIRED_COLUMNS, attach_fracture, read_fracture_csv
from oilgas.ml import fit_quantile_models, predict_volumes
from tests.fixtures.synthetic_panel import synthetic_panel

ML = load_config().ml
WELL_A, WELL_B, WELL_C = 200_001, 200_002, 200_003  # the first wells of the synthetic panel
HEADER = ",".join(["id_base_fractura_adjiv", *REQUIRED_COLUMNS])


def write_csv(path: Path, rows: list[dict]) -> Path:
    """A fracture file with the columns the project reads; each row is a dict (missing keys stay empty)."""
    lines = [HEADER]
    for n, row in enumerate(rows):
        lines.append(",".join([str(n), *(str(row.get(c, "")) for c in REQUIRED_COLUMNS)]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def frac(well: int, end: str, stages: float = 10, lateral: float = 1000, national: float = 100, imported: float = 50, water: float = 2000) -> dict:
    return {
        "idpozo": well, "fecha_fin_fractura": end, "cantidad_fracturas": stages, "longitud_rama_horizontal_m": lateral,
        "arena_bombeada_nacional_tn": national, "arena_bombeada_importada_tn": imported, "agua_inyectada_m3": water,
    }


@pytest.fixture()
def panel():
    return synthetic_panel(n_wells=8, n_months=36, seed=3)


def col_of(panel, year: int, month: int) -> int:
    return year * 12 + month - 1 - int(panel.period_index[0])


def test_the_reader_keeps_the_end_month_and_adds_national_and_imported_sand(tmp_path: Path) -> None:
    table = read_fracture_csv(write_csv(tmp_path / "f.csv", [frac(WELL_A, "2018-07-31", stages=12, lateral=0, national=300, imported=40, water=5000)]))
    assert table.well_id.tolist() == [WELL_A]
    assert table.end_index.tolist() == [2018 * 12 + 6]
    assert table.stages.tolist() == [12.0] and table.sand_t.tolist() == [340.0] and table.water_m3.tolist() == [5000.0]
    assert np.isnan(table.lateral_m[0])  # a lateral length of 0 is "not reported" (D15), not a short well


def test_rows_without_a_readable_end_date_are_dropped_and_counted(tmp_path: Path) -> None:
    rows = [frac(WELL_A, "2018-07-31"), frac(WELL_B, ""), frac(WELL_C, "not a date")]
    table = read_fracture_csv(write_csv(tmp_path / "f.csv", rows))
    assert table.well_id.tolist() == [WELL_A] and table.rows_dropped == 2  # without an end date nobody can prove it is not the future


def test_a_missing_column_is_named(tmp_path: Path) -> None:
    path = tmp_path / "f.csv"
    path.write_text("idpozo,fecha_fin_fractura\n1,2018-01-01\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cantidad_fracturas"):
        read_fracture_csv(path)


def test_values_appear_at_the_end_month_and_add_up_over_later_fractures(tmp_path: Path, panel) -> None:
    rows = [
        frac(WELL_A, "2018-06-30", stages=10, lateral=1000, national=100, imported=0, water=1000),
        frac(WELL_A, "2018-12-15", stages=5, lateral=1500, national=50, imported=10, water=500),
    ]
    attached = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "f.csv", rows)))
    well = np.array([0])
    before, first, between, second, later = (col_of(panel, 2018, m) for m in (5, 6, 9, 12, 12))
    assert all(np.isnan(features_at(attached, "oil", before, well)[name]).all() for name in FRACTURE_FEATURES)  # nothing known yet
    at_first = features_at(attached, "oil", first, well).iloc[0]
    assert (at_first.frac_stages, at_first.frac_lateral_m, at_first.frac_sand_t, at_first.frac_water_m3, at_first.frac_months_since) == (10, 1000, 100, 1000, 0)
    in_between = features_at(attached, "oil", between, well).iloc[0]
    assert (in_between.frac_stages, in_between.frac_months_since) == (10, 3)
    at_second = features_at(attached, "oil", second, well).iloc[0]
    assert (at_second.frac_stages, at_second.frac_lateral_m, at_second.frac_sand_t, at_second.frac_water_m3, at_second.frac_months_since) == (15, 1500, 160, 1500, 0)


def test_a_well_with_no_fracture_row_has_missing_values(tmp_path: Path, panel) -> None:
    attached = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "f.csv", [frac(WELL_A, "2018-06-30")])))
    frame = features_at(attached, "oil", 20)
    assert frame.loc[0, "frac_stages"] == 10 and frame.loc[1:, list(FRACTURE_FEATURES)].isna().all().all()


def test_a_fracture_after_the_last_month_of_the_panel_changes_nothing(tmp_path: Path, panel) -> None:
    only_past = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "a.csv", [frac(WELL_A, "2018-06-30")])))
    with_future = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "b.csv", [frac(WELL_A, "2018-06-30"), frac(WELL_A, "2030-01-31", stages=99)])))
    for key in only_past.fracture:
        np.testing.assert_array_equal(only_past.fracture[key], with_future.fracture[key])


def test_no_leakage_a_fracture_ending_after_the_origin_does_not_change_the_features_at_the_origin(tmp_path: Path, panel) -> None:
    """The same rule as AC11: perturbing everything after the origin leaves what is known at the origin untouched."""
    rows = [frac(WELL_A, "2018-06-30"), frac(WELL_B, "2018-08-31"), frac(WELL_C, "2019-02-28")]
    base = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "a.csv", rows)))
    origin = col_of(panel, 2018, 10)
    future = [frac(WELL_A, "2019-01-31", stages=77, water=9e6), frac(WELL_C, "2018-11-30", stages=55), frac(WELL_B, "2020-05-31", stages=66)]
    perturbed = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "b.csv", [*rows, *future])))
    pd.testing.assert_frame_equal(features_at(base, "oil", origin), features_at(perturbed, "oil", origin), check_exact=True)
    assert not features_at(base, "oil", origin + 1).equals(features_at(perturbed, "oil", origin + 1))  # the data did change afterwards


def test_training_examples_for_an_origin_only_know_fractures_ended_by_each_example_month(tmp_path: Path, panel) -> None:
    rows = [frac(WELL_A, "2018-06-30", stages=10), frac(WELL_A, "2019-03-31", stages=100)]
    attached = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "f.csv", rows)))
    origin = col_of(panel, 2018, 12)
    X, _ = training_examples(attached, "oil", 1, origin, dataclasses.replace(ML, train_window_months=12), 0.1)
    assert set(FRACTURE_FEATURES) <= set(X.columns)
    assert X["frac_stages"].dropna().isin([10.0]).all()  # the 2019 fracture is after the origin: it never reaches a training row


def test_without_fracture_data_the_features_are_exactly_the_base_ones(panel) -> None:
    frame = features_at(panel, "oil", 20)
    assert list(frame.columns) == FEATURE_COLUMNS
    assert panel.fracture is None


def test_the_models_train_and_predict_with_the_fracture_columns(tmp_path: Path, panel) -> None:
    rows = [frac(WELL_A, "2018-06-30"), frac(WELL_B, "2018-09-30", lateral=0)]
    attached = attach_fracture(panel, read_fracture_csv(write_csv(tmp_path / "f.csv", rows)))
    cfg = dataclasses.replace(ML, max_iter=5, min_samples_leaf=5, train_window_months=18)
    X, y = training_examples(attached, "oil", 1, 30, cfg, 0.1)
    models = fit_quantile_models(X, y, cfg)
    X_now = features_at(attached, "oil", 30, horizon=1)
    volumes = predict_volumes(models, X_now, np.full(len(X_now), 5.0), np.full(len(X_now), 30.0), 0.1)
    assert volumes.shape == (len(X_now), 3) and (volumes[:, 0] <= volumes[:, 1]).all() and (volumes[:, 1] <= volumes[:, 2]).all()


def test_the_option_is_off_by_default_and_names_the_file() -> None:
    cfg = load_config()
    assert cfg.ml.fracture_features is False
    assert cfg.paths.fracture_csv.name.startswith("datos-de-fractura")
