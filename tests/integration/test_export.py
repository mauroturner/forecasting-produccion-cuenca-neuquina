"""The model marts and the Parquet star schema on the synthetic warehouse (RF17, AC17)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from oilgas.dashboard.semantic_model import MODEL, arrow_schema
from oilgas.export import (
    MAX_PARQUET_BYTES,
    METADATA_KEYS,
    build_model_marts,
    export_star_schema,
    oversized_files,
    verify_star_schema,
)
from oilgas.warehouse import CheckFailedError, connect, run_checks

ATTRIBUTION = "Fuente: Secretaría de Energía (CC BY 4.0)."
MODEL_CHECKS = {
    "chk_backtest_metrics_nonnegative", "chk_forecast_fk", "chk_forecast_quantiles_ordered", "chk_model_dimensions_unique",
    "chk_model_facts_fk",
}


@pytest.fixture()
def conn(modeled_copy: Path):
    connection = connect(modeled_copy)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def exported(tmp_path_factory, modeled_warehouse):
    """The star schema exported once from a private copy (read-only for the tests of this module)."""
    import shutil

    root = tmp_path_factory.mktemp("star")
    copy = root / "production.sqlite"
    shutil.copy(modeled_warehouse, copy)
    connection = connect(copy)
    paths = export_star_schema(connection, root / "powerbi", MODEL, "r1", "ab" * 32, ATTRIBUTION)
    yield root / "powerbi", paths
    connection.close()


def count(conn: sqlite3.Connection, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


# --- the marts --------------------------------------------------------------------------------------------------


def test_the_model_controls_are_the_ones_of_the_plan(conn) -> None:
    from oilgas import warehouse

    names = {p.stem for p in (warehouse.SQL_DIR / "checks" / "model").glob("chk_*.sql")}
    assert names == MODEL_CHECKS


def test_building_the_marts_creates_every_model_table_and_the_controls_pass(conn) -> None:
    build_model_marts(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {t.name for t in MODEL.tables} <= tables
    results = run_checks(conn, "model")
    assert {c.check_id for c in results} == MODEL_CHECKS and all(c.violations == 0 for c in results)


def test_the_small_dimensions_hold_the_values_of_the_plan(conn) -> None:
    build_model_marts(conn)
    assert conn.execute("SELECT fluid_key, fluid_name_es, unit FROM dim_fluid ORDER BY fluid_key").fetchall() == [
        ("gas", "Gas", "miles de m³"), ("oil", "Petróleo", "m³"),
    ]
    assert [r[0] for r in conn.execute("SELECT method_key FROM dim_method ORDER BY sort_order")] == [
        "naive_last", "naive_mean3", "arps_exp", "arps_mh_b2", "arps_mh_b1", "ml_hgb",
    ]
    assert {r[0]: r[1] for r in conn.execute("SELECT method_key, is_base FROM dim_method")} == {
        "naive_last": 1, "naive_mean3": 1, "arps_exp": 0, "arps_mh_b2": 0, "arps_mh_b1": 0, "ml_hgb": 0,
    }
    assert {r[0] for r in conn.execute("SELECT family FROM dim_method")} == {"Línea base", "Arps", "Machine learning"}
    horizons = conn.execute("SELECT horizon, horizon_label, is_headline FROM dim_horizon ORDER BY horizon").fetchall()
    assert [h[0] for h in horizons] == list(range(1, 13)) and horizons[0][1:] == ("1 mes", 1) and horizons[2][1:] == ("3 meses", 1)
    assert [h[0] for h in horizons if h[2]] == [1, 3, 6, 12]
    origin = conn.execute("SELECT origin_period_key, origin_label, is_latest, run_key FROM dim_origin").fetchall()
    assert origin == [(202412, "2024-12", 1, "r1")]


def test_the_facts_mirror_the_model_tables_with_renamed_keys(conn) -> None:
    build_model_marts(conn)
    assert count(conn, "SELECT COUNT(*) FROM fact_forecast") == count(conn, "SELECT COUNT(*) FROM model_forecast") > 0
    assert count(conn, "SELECT COUNT(*) FROM fact_well_fit") == count(conn, "SELECT COUNT(*) FROM model_fit") > 0
    assert count(conn, "SELECT COUNT(*) FROM fact_fitted_curve") == count(conn, "SELECT COUNT(*) FROM model_fitted_curve") > 0
    assert count(conn, "SELECT COUNT(*) FROM fact_backtest_metrics") == count(conn, "SELECT COUNT(*) FROM model_backtest_metrics") > 0
    assert count(conn, "SELECT COUNT(*) FROM fact_model_summary") == count(conn, "SELECT COUNT(*) FROM model_summary") > 0
    assert count(conn, "SELECT COUNT(*) FROM dim_pipeline_run") == 1
    one = conn.execute("SELECT well_key, fluid_key, method_key, p50 FROM fact_forecast LIMIT 1").fetchone()
    assert conn.execute(
        "SELECT p50 FROM model_forecast WHERE well_id = ? AND fluid = ? AND method = ? LIMIT 1", one[:3]
    ).fetchone()[0] == one[3]
    needs = conn.execute("SELECT COUNT(*) FROM fact_well_fit WHERE needs_review = 1").fetchone()[0]
    assert needs == count(conn, "SELECT COUNT(*) FROM model_fit WHERE rmse_log > 1.0")


def test_the_validation_status_says_pasa_falla_or_advierte(conn) -> None:
    build_model_marts(conn)
    status = {r[0]: r[1] for r in conn.execute("SELECT rule_id, status FROM fact_validation")}
    assert status["V01"] == "pasa" and status["V12"] == "advierte" and status["I01"] == "pasa"
    conn.execute("UPDATE validation_results SET passed = 0 WHERE rule_id = 'V04'")
    build_model_marts(conn)
    assert conn.execute("SELECT status FROM fact_validation WHERE rule_id = 'V04'").fetchone()[0] == "falla"


def test_only_the_latest_twelve_origins_reach_the_facts(conn) -> None:
    older = [*range(202301, 202313), 202401, 202402]  # fourteen older origins, copies of the real one
    for key in older:
        conn.execute(
            "INSERT INTO model_forecast SELECT ?, well_id, fluid, method, horizon, 'old', target_period_key, company_code, "
            "p10, p50, p90, segment, 0, fit_status FROM model_forecast WHERE origin_period_key = 202412",
            (key,),
        )
    build_model_marts(conn)
    origins = [r[0] for r in conn.execute("SELECT origin_period_key FROM dim_origin ORDER BY origin_period_key")]
    assert origins == [*older[3:], 202412]  # the latest twelve of the fifteen
    assert {r[0] for r in conn.execute("SELECT DISTINCT origin_period_key FROM fact_forecast")} == set(origins)
    assert conn.execute("SELECT origin_label FROM dim_origin WHERE origin_period_key = 202304").fetchone()[0] == "2023-04"
    assert conn.execute("SELECT is_latest FROM dim_origin WHERE origin_period_key = 202412").fetchone()[0] == 1
    assert count(conn, "SELECT COUNT(*) FROM dim_origin WHERE is_latest = 1") == 1
    assert count(conn, "SELECT COUNT(*) FROM model_forecast") > count(conn, "SELECT COUNT(*) FROM fact_forecast")  # the older ones stay


def test_rebuilding_the_marts_gives_the_same_content(conn) -> None:
    build_model_marts(conn)
    first = {t.name: conn.execute(f"SELECT * FROM {t.name} ORDER BY {', '.join(t.key)}").fetchall() for t in MODEL.tables}
    build_model_marts(conn)
    second = {t.name: conn.execute(f"SELECT * FROM {t.name} ORDER BY {', '.join(t.key)}").fetchall() for t in MODEL.tables}
    assert first == second


def test_building_the_marts_needs_a_loaded_publication(tmp_path: Path) -> None:
    empty = connect(tmp_path / "empty.sqlite")
    with pytest.raises(RuntimeError, match="load a validated publication"):
        build_model_marts(empty)
    empty.close()


@pytest.mark.parametrize(
    ("tamper", "check"),
    [
        ("UPDATE model_forecast SET p10 = p50 + 1 WHERE rowid = (SELECT MIN(rowid) FROM model_forecast)", "chk_forecast_quantiles_ordered"),
        ("UPDATE model_forecast SET p10 = -1, p50 = 0 WHERE rowid = (SELECT MIN(rowid) FROM model_forecast)", "chk_forecast_quantiles_ordered"),
        ("UPDATE model_forecast SET well_id = 999999999 WHERE rowid = (SELECT MIN(rowid) FROM model_forecast)", "chk_forecast_fk"),
        ("UPDATE model_forecast SET target_period_key = 209912 WHERE rowid = (SELECT MIN(rowid) FROM model_forecast)", "chk_forecast_fk"),
        ("UPDATE model_forecast SET method = 'magic' WHERE rowid = (SELECT MIN(rowid) FROM model_forecast)", "chk_forecast_fk"),
        ("UPDATE model_backtest_metrics SET sum_abs_error = -1 WHERE rowid = (SELECT MIN(rowid) FROM model_backtest_metrics)", "chk_backtest_metrics_nonnegative"),
        ("UPDATE model_backtest_metrics SET n_covered = n + 1 WHERE rowid = (SELECT MIN(rowid) FROM model_backtest_metrics)", "chk_backtest_metrics_nonnegative"),
        ("UPDATE model_fit SET well_id = 999999999 WHERE rowid = (SELECT MIN(rowid) FROM model_fit)", "chk_model_facts_fk"),
        ("UPDATE model_summary SET horizon = 99 WHERE rowid = (SELECT MIN(rowid) FROM model_summary)", "chk_model_facts_fk"),
        ("UPDATE validation_results SET run_key = 'no-such-run' WHERE rule_id = 'V01'", "chk_model_facts_fk"),
    ],
)
def test_a_broken_model_table_fails_its_control_and_the_marts_keep_what_they_had(conn, tamper: str, check: str) -> None:
    build_model_marts(conn)
    before = conn.execute("SELECT COUNT(*), SUM(p50) FROM fact_forecast").fetchone()
    conn.execute(tamper)
    with pytest.raises(CheckFailedError, match=check) as info:
        build_model_marts(conn)
    assert any(c.check_id == check and c.violations > 0 for c in info.value.checks)
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*), SUM(p50) FROM fact_forecast").fetchone() == before  # rolled back to the previous marts


# --- the Parquet files ------------------------------------------------------------------------------------------


def test_one_file_per_table_of_the_model_in_its_order(exported) -> None:
    out_dir, paths = exported
    assert [p.name for p in paths] == [f"{t.name}.parquet" for t in MODEL.tables]
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(p.name for p in paths)  # no temporary file is left


def test_every_file_has_the_schema_of_the_model_and_the_metadata(exported) -> None:
    _, paths = exported
    for table, path in zip(MODEL.tables, paths, strict=True):
        schema = pq.read_schema(path)
        assert schema.equals(arrow_schema(table), check_metadata=False), table.name
        metadata = {k.decode(): v.decode() for k, v in schema.metadata.items()}
        assert metadata["oilgas.run_key"] == "r1" and metadata["oilgas.source_sha256"] == "ab" * 32
        assert metadata["oilgas.attribution"] == ATTRIBUTION
        assert set(METADATA_KEYS) <= set(metadata)


def test_the_star_schema_keeps_the_contract_from_the_files(exported) -> None:
    out_dir, _ = exported
    assert verify_star_schema(out_dir, MODEL) == []  # keys, grains, integrity of the 25 relationships, DAX references


def test_the_values_are_the_ones_of_the_warehouse(exported, conn) -> None:
    out_dir, _ = exported
    calendar = pq.read_table(out_dir / "dim_calendar.parquet")
    assert calendar.schema.field("month_start").type == pa.date32() and calendar.schema.field("is_published").type == pa.bool_()
    frame = calendar.to_pandas()
    assert str(frame["month_start"].iloc[0]) == "2018-01-01" and frame["is_published"].sum() == 84 and frame["is_last_published"].sum() == 1
    production = pq.read_table(out_dir / "fact_production_monthly.parquet")
    assert production.num_rows == count(conn, "SELECT COUNT(*) FROM stg_monthly_production")
    forecast = pq.read_table(out_dir / "fact_forecast.parquet").to_pandas()
    assert len(forecast) == count(conn, "SELECT COUNT(*) FROM model_forecast")
    assert forecast["is_selected"].dtype == bool and forecast["horizon"].between(1, 12).all()
    assert (forecast["p10"] <= forecast["p50"]).all() and (forecast["p50"] <= forecast["p90"]).all()
    run = pq.read_table(out_dir / "dim_pipeline_run.parquet").to_pandas()
    assert run["run_key"].tolist() == ["r1"] and run["last_period_key"].iloc[0] == 202412 and run["source_size"].iloc[0] == 1234


def test_missing_values_are_nulls_not_nan(exported) -> None:
    out_dir, _ = exported
    fit = pq.read_table(out_dir / "fact_well_fit.parquet")
    naive = [i for i, status in enumerate(fit["status"].to_pylist()) if status == "fallback_naive"]
    column = fit["log_qi"]
    assert column.null_count == len(naive)  # a failed fit has no parameters: null, which Power BI shows as blank
    assert all(v is None or v == v for v in column.to_pylist())  # and no NaN hides in the numbers


def test_exporting_twice_gives_files_with_the_same_content(exported, tmp_path, conn) -> None:
    out_dir, _ = exported
    again = export_star_schema(conn, tmp_path / "again", MODEL, "r1", "ab" * 32, ATTRIBUTION)
    for path in again:
        assert pq.read_table(path).equals(pq.read_table(out_dir / path.name)), path.name


def test_the_files_stay_below_the_limit_for_a_versioned_file(exported) -> None:
    _, paths = exported
    assert oversized_files(paths) == []
    assert MAX_PARQUET_BYTES == 25 * 1024 * 1024
    assert oversized_files(paths, limit=1_000) == [p for p in paths if p.stat().st_size > 1_000] != []


def test_a_failing_control_stops_the_export_before_it_writes_anything(conn, tmp_path, exported) -> None:
    out_dir = tmp_path / "powerbi"
    export_star_schema(conn, out_dir, MODEL, "r1", "ab" * 32, ATTRIBUTION)
    before = {p.name: p.read_bytes() for p in out_dir.iterdir()}
    conn.execute("UPDATE model_forecast SET p10 = p50 + 1 WHERE rowid = (SELECT MIN(rowid) FROM model_forecast)")
    with pytest.raises(CheckFailedError, match="chk_forecast_quantiles_ordered"):
        export_star_schema(conn, out_dir, MODEL, "r2", "cd" * 32, ATTRIBUTION)
    assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == before  # the previous files, byte for byte


def test_exporting_an_inconsistent_model_is_refused(conn, tmp_path) -> None:
    import dataclasses

    relationships = list(MODEL.relationships)
    relationships[0] = dataclasses.replace(relationships[0], cross_filter="both")
    with pytest.raises(ValueError, match="inconsistent"):
        export_star_schema(conn, tmp_path / "x", dataclasses.replace(MODEL, relationships=tuple(relationships)), "r1", "ab" * 32, ATTRIBUTION)
    assert not (tmp_path / "x").exists()


def test_the_export_logs_each_file(conn, tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="oilgas.export")
    export_star_schema(conn, tmp_path / "powerbi", MODEL, "r1", "ab" * 32, ATTRIBUTION)
    messages = [r.getMessage() for r in caplog.records if r.name == "oilgas.export"]
    assert any(m.startswith("exported fact_forecast.parquet:") and "rows" in m for m in messages)


# --- the verification catches a tampered file ---------------------------------------------------------------------


def copy_files(out_dir: Path, target: Path) -> Path:
    target.mkdir()
    for path in out_dir.iterdir():
        (target / path.name).write_bytes(path.read_bytes())
    return target


def rewrite(path: Path, change) -> None:
    table = pq.read_table(path)
    frame = change(table.to_pandas())
    pq.write_table(pa.Table.from_pandas(frame, schema=table.schema, preserve_index=False).replace_schema_metadata(table.schema.metadata), path)


def test_a_duplicate_dimension_key_is_reported(exported, tmp_path) -> None:
    files = copy_files(exported[0], tmp_path / "f")
    rewrite(files / "dim_company.parquet", lambda f: pd.concat([f, f.iloc[[0]]], ignore_index=True))
    assert any("dim_company" in p and "not unique" in p for p in verify_star_schema(files, MODEL))


def test_a_foreign_key_without_its_dimension_row_is_reported(exported, tmp_path) -> None:
    files = copy_files(exported[0], tmp_path / "f")

    def orphan(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame.loc[frame.index[0], "well_key"] = 987654321
        return frame

    rewrite(files / "fact_forecast.parquet", orphan)
    problems = verify_star_schema(files, MODEL)
    assert any("fact_forecast[well_key]" in p and "1 values not in dim_well" in p for p in problems)


def test_an_empty_foreign_key_is_reported(exported, tmp_path) -> None:
    files = copy_files(exported[0], tmp_path / "f")

    def blank(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame.loc[frame.index[0], "company_key"] = None
        return frame

    rewrite(files / "fact_production_monthly.parquet", blank)
    assert any("fact_production_monthly[company_key]" in p and "1 empty" in p for p in verify_star_schema(files, MODEL))


def test_a_changed_schema_a_missing_file_and_missing_metadata_are_reported(exported, tmp_path) -> None:
    files = copy_files(exported[0], tmp_path / "f")
    table = pq.read_table(files / "dim_fluid.parquet")
    pq.write_table(table.drop_columns(["unit"]), files / "dim_fluid.parquet")
    (files / "dim_horizon.parquet").unlink()
    bare = pq.read_table(files / "dim_method.parquet").replace_schema_metadata({})
    pq.write_table(bare, files / "dim_method.parquet")
    problems = verify_star_schema(files, MODEL)
    assert any("dim_fluid" in p and "schema" in p for p in problems)
    assert any("dim_horizon" in p and "does not exist" in p for p in problems)
    assert any("dim_method" in p and "metadata" in p for p in problems)


# --- the size limit of a versioned file (RNF09) ---------------------------------------------------------------------


def add_older_origins(conn: sqlite3.Connection, keys) -> None:
    """Older origins that are copies of the real one with their volumes scaled by a factor that changes from row to row (so they do not compress away)."""
    for key in keys:
        conn.execute(
            "INSERT INTO model_forecast "
            "WITH scaled AS (SELECT *, 1 + ((rowid * 7919 + ?) % 1000) / 1000.0 AS f FROM model_forecast WHERE origin_period_key = 202412) "
            "SELECT ?, well_id, fluid, method, horizon, 'old', target_period_key, company_code, p10 * f, p50 * f, p90 * f, "
            "segment, 0, fit_status FROM scaled",
            (key, key),
        )


def test_the_origins_kept_shrink_when_a_file_that_grows_with_them_would_pass_the_limit(conn, tmp_path, monkeypatch, caplog) -> None:
    from oilgas import export

    add_older_origins(conn, [*range(202301, 202313)])
    full = export_star_schema(conn, tmp_path / "full", MODEL, "r1", "ab" * 32, ATTRIBUTION)
    full_size = next(p for p in full if p.name == "fact_forecast.parquet").stat().st_size
    assert pq.read_table(next(p for p in full if p.name == "dim_origin.parquet")).num_rows == 12
    monkeypatch.setattr(export, "MAX_PARQUET_BYTES", full_size // 3)  # three times too small for twelve origins
    caplog.set_level(logging.WARNING, logger="oilgas.export")
    paths = export_star_schema(conn, tmp_path / "small", MODEL, "r1", "ab" * 32, ATTRIBUTION)
    by_name = {p.name: p for p in paths}
    assert by_name["fact_forecast.parquet"].stat().st_size <= full_size // 3
    kept = pq.read_table(by_name["dim_origin.parquet"]).to_pandas()["origin_period_key"].tolist()
    assert 1 <= len(kept) < 12 and kept[-1] == 202412  # the latest origins are the ones that stay
    assert set(pq.read_table(by_name["fact_forecast.parquet"]).to_pandas()["origin_period_key"]) == set(kept)
    assert set(pq.read_table(by_name["fact_well_fit.parquet"]).to_pandas()["origin_period_key"]) <= set(kept)
    assert verify_star_schema(tmp_path / "small", MODEL) == []  # still a consistent star
    assert any("keeping the latest" in r.getMessage() for r in caplog.records)
    assert oversized_files([by_name["fact_forecast.parquet"]]) == []
    assert conn.execute("SELECT COUNT(DISTINCT origin_period_key) FROM model_forecast").fetchone()[0] == 13  # SQLite keeps them all


def test_one_origin_is_always_kept_even_if_it_alone_passes_the_limit(conn, tmp_path, monkeypatch, caplog) -> None:
    from oilgas import export

    add_older_origins(conn, [202301, 202302])
    monkeypatch.setattr(export, "MAX_PARQUET_BYTES", 1)
    paths = export_star_schema(conn, tmp_path / "tiny", MODEL, "r1", "ab" * 32, ATTRIBUTION)
    origins = pq.read_table(next(p for p in paths if p.name == "dim_origin.parquet")).to_pandas()["origin_period_key"].tolist()
    assert origins == [202412]
    assert {p.name for p in oversized_files(paths)} >= {"fact_forecast.parquet"}  # reported, not hidden
