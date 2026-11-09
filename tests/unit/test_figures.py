"""The documentation figures (plan section 17) drawn from the modeled warehouse: files, data and failures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib.image as mpimg
import pandas as pd
import pytest

from oilgas import figures
from oilgas.warehouse import connect

EXPECTED = ["example_well_fit.png", "method_comparison.png", "coverage.png", "basin_forecast.png"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture()
def conn(modeled_warehouse: Path):
    connection = connect(modeled_warehouse)
    yield connection
    connection.close()


@pytest.fixture()
def drawn(conn, tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    out = tmp_path / "figures"
    return figures.make_figures(conn, reports, out), out


def test_the_four_figures_of_the_documentation_are_written_as_png(drawn) -> None:
    paths, out = drawn
    assert [p.name for p in paths] == EXPECTED
    for path in paths:
        assert path.parent == out
        assert path.read_bytes()[:8] == PNG_SIGNATURE
        height, width = mpimg.imread(path).shape[:2]
        assert width >= 900 and height >= 450  # readable in a README at full width


def test_drawing_twice_gives_the_same_files(conn, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    first = [p.read_bytes() for p in figures.make_figures(conn, reports, tmp_path / "a")]
    second = [p.read_bytes() for p in figures.make_figures(conn, reports, tmp_path / "b")]
    assert first == second  # a versioned figure changes only when the data does


def test_the_example_well_is_the_largest_producer_among_the_wells_with_a_base_fit(conn) -> None:
    well = figures.example_well(conn)
    fits = pd.read_sql_query(
        "SELECT well_id FROM model_fit WHERE fluid = 'oil' AND method = 'arps_mh_b2' AND status = 'ok' "
        "AND origin_period_key = (SELECT MAX(origin_period_key) FROM model_fit)", conn)
    wells = pd.read_sql_query("SELECT well_key, cum_oil_m3 FROM dim_well", conn).set_index("well_key")
    expected = wells.loc[fits["well_id"].tolist(), "cum_oil_m3"].idxmax()
    assert well == int(expected)


def test_the_basin_projection_adds_the_selected_method_of_every_well(conn) -> None:
    for fluid in ("oil", "gas"):
        produced, projected = figures.basin_series(conn, fluid)
        origin = conn.execute("SELECT MAX(origin_period_key) FROM model_forecast").fetchone()[0]
        rows = pd.read_sql_query(
            "SELECT target_period_key AS k, SUM(p10) AS p10, SUM(p50) AS p50, SUM(p90) AS p90 FROM model_forecast "
            "WHERE fluid = ? AND is_selected = 1 AND origin_period_key = ? GROUP BY target_period_key ORDER BY k", conn, params=(fluid, origin))
        assert len(rows) == 12
        assert projected["period_key"].tolist() == rows["k"].tolist()
        for column in ("p10", "p50", "p90"):
            assert projected[column].tolist() == pytest.approx(rows[column].tolist())
        assert (projected["p10"] <= projected["p50"]).all() and (projected["p50"] <= projected["p90"]).all()
        assert produced["period_key"].max() == origin  # the history ends where the projection starts
        assert projected["period_key"].min() > origin


def test_the_coverage_target_comes_from_the_summary_of_the_run(conn, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    assert figures.coverage_target(reports) == 0.8  # no summary yet: the preregistered default
    (reports / "backtest_summary.json").write_text(json.dumps({"criteria": {"thresholds": {"coverage_target": 0.75, "coverage_acceptable": [0.6, 0.9]}}}), encoding="utf-8")
    assert figures.coverage_target(reports) == 0.75


def test_a_warehouse_without_a_backtest_says_to_run_the_pipeline(warehouse_path: Path, tmp_path: Path) -> None:
    copy = tmp_path / "empty.sqlite"
    shutil.copy(warehouse_path, copy)
    connection = connect(copy)
    try:
        with pytest.raises(ValueError, match="run the pipeline"):
            figures.make_figures(connection, tmp_path, tmp_path / "out")
    finally:
        connection.close()
    assert not (tmp_path / "out").exists()  # nothing half written


def test_a_failure_while_drawing_leaves_no_partial_file(conn, tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "figures"
    monkeypatch.setattr(figures, "basin_series", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        figures.make_figures(conn, tmp_path, out)
    assert not out.exists()  # every figure is drawn before the first one is written


def test_every_figure_has_content_and_not_just_an_empty_frame(drawn) -> None:
    paths, _ = drawn
    assert all(p.stat().st_size > 20_000 for p in paths)
