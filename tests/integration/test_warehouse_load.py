"""Loading the validated subset into SQLite (RF05, RF06, AC05, AC06)."""

from __future__ import annotations

import shutil
import sqlite3
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from oilgas import warehouse
from oilgas.config import load_config
from oilgas.schema import read_source_csv
from oilgas.validate import PreviousLoad, validate_file
from oilgas.warehouse import (
    CheckFailedError,
    LoadResult,
    apply_schema,
    connect,
    load_validated_subset,
    previous_load,
    run_checks,
)
from tests.fixtures.make_fixture import FixtureTruth

CFG = load_config()
TODAY = date(2025, 1, 15)
PRODUCTION_CHECKS = {
    "chk_stg_unique_key", "chk_stg_period_range", "chk_stg_nonnegative", "chk_stg_effective_days",
    "chk_dim_well_unique", "chk_dim_company_unique", "chk_dim_calendar_contiguous",
    "chk_fact_production_fk_well", "chk_fact_production_fk_company", "chk_fact_production_fk_calendar",
}
MAIN_TABLES = ("raw_monthly_production", "stg_monthly_production", "dim_calendar", "dim_company", "dim_well", "fact_production_monthly")
SNAPSHOT_TABLES = (
    "raw_monthly_production", "stg_monthly_production", "dim_calendar", "dim_company", "dim_well",
    "fact_production_monthly", "load_revisions", "period_totals",
)


def snapshot(conn: sqlite3.Connection, tables=SNAPSHOT_TABLES, skip: tuple[str, ...] = ()) -> dict[str, list]:
    out = {}
    for table in tables:
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] not in skip]
        if not columns:
            out[table] = []
            continue
        select = ", ".join(columns)
        out[table] = conn.execute(f"SELECT {select} FROM {table} ORDER BY {select}").fetchall()
    return out


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


@pytest.fixture(scope="module")
def loaded(tmp_path_factory, valid_frame):
    """A warehouse with the valid fixture loaded as r1."""
    conn = connect(tmp_path_factory.mktemp("wh") / "production.sqlite")
    result = load_validated_subset(conn, valid_frame, "r1")
    yield conn, result
    conn.close()


@pytest.fixture()
def empty(tmp_path: Path):
    conn = connect(tmp_path / "production.sqlite")
    yield conn
    conn.close()


# --- the load (AC05) --------------------------------------------------------------------------------


def test_load_result_counts_the_subset(loaded, valid_report) -> None:
    _, result = loaded
    assert isinstance(result, LoadResult)
    assert result.rows == valid_report.rows_subset
    assert result.wells == valid_report.wells_subset == 60
    assert result.last_period_key == valid_report.last_period_key == 202412
    assert result.revised_rows == 0  # first load: nothing to revise
    assert {c.check_id for c in result.checks} == PRODUCTION_CHECKS
    assert all(c.violations == 0 and c.sample == [] for c in result.checks)


def test_staging_has_one_row_per_validated_row_and_one_per_well_and_month(loaded, valid_report) -> None:
    conn, _ = loaded
    assert conn.execute("SELECT COUNT(*) FROM stg_monthly_production").fetchone()[0] == valid_report.rows_subset
    assert conn.execute("SELECT COUNT(*) FROM raw_monthly_production").fetchone()[0] == valid_report.rows_subset
    assert conn.execute("SELECT COUNT(DISTINCT well_id) FROM stg_monthly_production").fetchone()[0] == valid_report.wells_subset
    assert conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM stg_monthly_production GROUP BY well_id, period_key)").fetchone()[0] == valid_report.rows_subset


def test_the_controls_return_nothing_on_the_loaded_warehouse(loaded) -> None:
    conn, _ = loaded
    assert {c.check_id: c.violations for c in run_checks(conn, "production")} == dict.fromkeys(PRODUCTION_CHECKS, 0)


def test_raw_keeps_the_published_values_and_stg_the_corrected_ones(loaded, valid_frame, fixture_truth: FixtureTruth) -> None:
    conn, _ = loaded
    well, period = fixture_truth.negative_gas_rows[0]
    assert conn.execute("SELECT gas_thousand_m3 FROM raw_monthly_production WHERE well_id=? AND period_key=?", (well, period)).fetchone() == (-12.5,)
    gas, flags, producing = conn.execute(
        "SELECT gas_thousand_m3, quality_flags, is_producing FROM stg_monthly_production WHERE well_id=? AND period_key=?",
        (well, period),
    ).fetchone()
    assert gas is None and flags == "NEG_VOLUME" and producing == 1  # oil still positive
    well, period = fixture_truth.tef_gt_days_rows[0]
    tef, flags = conn.execute("SELECT effective_days, quality_flags FROM stg_monthly_production WHERE well_id=? AND period_key=?", (well, period)).fetchone()
    assert tef is None and flags == "TEF_GT_DAYS"
    for well, period in fixture_truth.tef_zero_with_production_rows:
        tef, flags = conn.execute("SELECT effective_days, quality_flags FROM stg_monthly_production WHERE well_id=? AND period_key=?", (well, period)).fetchone()
        assert tef == 0 and flags == "TEF_ZERO_WITH_PROD"
    assert conn.execute("SELECT COUNT(*) FROM stg_monthly_production WHERE quality_flags <> ''").fetchone()[0] == 4


def test_staging_computes_days_and_is_producing(loaded) -> None:
    conn, _ = loaded
    assert conn.execute("SELECT DISTINCT days_in_month FROM stg_monthly_production WHERE period_key = 202402").fetchall() == [(29,)]
    assert conn.execute("SELECT DISTINCT days_in_month FROM stg_monthly_production WHERE period_key = 202302").fetchall() == [(28,)]
    assert conn.execute(
        "SELECT COUNT(*) FROM stg_monthly_production WHERE is_producing <> (COALESCE(oil_m3,0) > 0 OR COALESCE(gas_thousand_m3,0) > 0)"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM stg_monthly_production WHERE is_producing = 0").fetchone()[0] > 0  # the zero months


def test_dim_calendar_runs_from_the_first_period_to_twelve_months_after_the_last(loaded) -> None:
    conn, _ = loaded
    rows = conn.execute("SELECT * FROM dim_calendar ORDER BY period_index").fetchall()
    names = [d[0] for d in conn.execute("SELECT * FROM dim_calendar").description]
    assert names == [
        "period_key", "period_index", "month_start", "year", "month", "month_name_es", "quarter",
        "year_month_label", "days_in_month", "is_published", "is_last_published",
    ]
    first, last = rows[0], rows[-1]
    assert (first[0], last[0]) == (201801, 202512)
    assert len(rows) == 84 + 12
    assert [r[1] for r in rows] == list(range(first[1], first[1] + len(rows)))
    assert sum(r[9] for r in rows) == 84 and sum(r[10] for r in rows) == 1
    assert [r[0] for r in rows if r[10]] == [202412] and all(r[9] == 0 for r in rows if r[0] > 202412)
    march = next(r for r in rows if r[0] == 202403)
    assert march == (202403, 2024 * 12 + 2, "2024-03-01", 2024, 3, "Marzo", 1, "2024-03", 31, 1, 0)
    assert next(r for r in rows if r[0] == 202402)[8] == 29
    assert next(r for r in rows if r[0] == 202410)[6] == 4 and next(r for r in rows if r[0] == 202412)[5] == "Diciembre"


def test_dim_company_has_one_row_per_operator_with_the_latest_name(loaded, valid_frame) -> None:
    conn, _ = loaded
    rows = dict(conn.execute("SELECT company_key, company_name FROM dim_company").fetchall())
    assert set(rows) == set(valid_frame["company_code"].dropna().unique())
    for code, name in rows.items():
        latest = valid_frame[valid_frame["company_code"] == code].sort_values("period_key").iloc[-1]
        assert name == latest["company_name"]


def test_dim_well_columns_and_aggregates(loaded, valid_frame, fixture_truth: FixtureTruth) -> None:
    conn, _ = loaded
    cursor = conn.execute("SELECT * FROM dim_well ORDER BY well_key")
    names = [d[0] for d in cursor.description]
    assert names == [
        "well_key", "well_code", "province", "concession_code", "concession_name", "field_code", "field_name",
        "formation_code", "formation_name", "sub_resource_type", "basin", "lon", "lat", "depth_m",
        "operator_current_key", "operator_current_name", "well_type_latest", "well_status_latest",
        "extraction_method_latest", "first_production_period_key", "last_report_period_key",
        "months_with_production", "cum_oil_m3", "cum_gas_thousand_m3", "cum_water_m3", "quality_flags",
    ]
    wells = {r[0]: dict(zip(names, r, strict=True)) for r in cursor.fetchall()}
    assert set(wells) == set(fixture_truth.wells)
    for well_id, record in wells.items():
        own = valid_frame[valid_frame["well_id"] == well_id].sort_values("period_key")
        gas = own["gas_thousand_m3"].where(own["gas_thousand_m3"] >= 0)
        producing = (own["oil_m3"].fillna(0) > 0) | (gas.fillna(0) > 0)
        assert record["months_with_production"] == int(producing.sum())
        assert record["first_production_period_key"] == int(own.loc[producing, "period_key"].min())
        assert record["last_report_period_key"] == int(own["period_key"].max())
        assert record["cum_oil_m3"] == pytest.approx(own["oil_m3"].sum())
        assert record["cum_gas_thousand_m3"] == pytest.approx(gas.sum())
        assert record["cum_water_m3"] == pytest.approx(own["water_m3"].sum())
        assert record["operator_current_key"] == own.iloc[-1]["company_code"]
        assert record["well_code"] == own.iloc[-1]["well_code"]
    for well_id in fixture_truth.operator_change_wells:
        own = valid_frame[valid_frame["well_id"] == well_id]
        assert own["company_code"].nunique() == 2
        assert wells[well_id]["quality_flags"] == ""  # changing operator is not a data problem


def test_dim_well_corrects_and_marks_coordinates_and_depth(loaded, valid_frame, fixture_truth: FixtureTruth) -> None:
    conn, _ = loaded
    swapped = fixture_truth.swapped_coords_well
    lon, lat, flags = conn.execute("SELECT lon, lat, quality_flags FROM dim_well WHERE well_key = ?", (swapped,)).fetchone()
    original = valid_frame[valid_frame["well_id"] == swapped].iloc[-1]
    assert (lon, lat) == (original["lat"], original["lon"]) and -71.5 <= lon <= -66.0 and -41.5 <= lat <= -34.5
    assert flags == "COORDS_SWAPPED"
    for well in fixture_truth.depth_invalid_wells:
        depth, flags = conn.execute("SELECT depth_m, quality_flags FROM dim_well WHERE well_key = ?", (well,)).fetchone()
        assert depth is None and flags == "DEPTH_INVALID"
    assert conn.execute("SELECT COUNT(*) FROM dim_well WHERE quality_flags <> ''").fetchone()[0] == 3


def test_fact_production_monthly_mirrors_staging_with_the_run_key(loaded, valid_report) -> None:
    conn, _ = loaded
    cursor = conn.execute("SELECT * FROM fact_production_monthly")
    assert [d[0] for d in cursor.description] == [
        "well_key", "period_key", "company_key", "oil_m3", "gas_thousand_m3", "water_m3", "effective_days",
        "is_producing", "well_type", "well_status", "extraction_method", "quality_flags", "run_key",
    ]
    assert len(cursor.fetchall()) == valid_report.rows_subset
    assert conn.execute("SELECT DISTINCT run_key FROM fact_production_monthly").fetchall() == [("r1",)]
    assert conn.execute(
        "SELECT COUNT(*) FROM fact_production_monthly AS f JOIN stg_monthly_production AS s "
        "ON s.well_id = f.well_key AND s.period_key = f.period_key "
        "WHERE f.oil_m3 IS NOT s.oil_m3 OR f.gas_thousand_m3 IS NOT s.gas_thousand_m3 OR f.quality_flags <> s.quality_flags"
    ).fetchone()[0] == 0


def test_period_totals_are_recorded_for_the_run(loaded, valid_frame) -> None:
    conn, _ = loaded
    expected = valid_frame.groupby("period_key").agg(oil=("oil_m3", "sum"), gas=("gas_thousand_m3", "sum"), rows=("well_id", "size"))
    stored = conn.execute("SELECT period_key, oil_m3, gas_thousand_m3, rows FROM period_totals WHERE run_key = 'r1' ORDER BY period_key").fetchall()
    assert [r[0] for r in stored] == list(expected.index)
    assert [r[3] for r in stored] == list(expected["rows"])
    assert [r[1] for r in stored] == pytest.approx(list(expected["oil"]))
    assert [r[2] for r in stored] == pytest.approx(list(expected["gas"]))


# --- idempotence ------------------------------------------------------------------------------------


def test_reloading_the_same_publication_leaves_the_same_content(tmp_path: Path, valid_frame) -> None:
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1")
    before = snapshot(conn, MAIN_TABLES, skip=("run_key",))
    second = load_validated_subset(conn, valid_frame, "r2")
    after = snapshot(conn, MAIN_TABLES, skip=("run_key",))
    assert before == after
    assert second.revised_rows == 0
    assert conn.execute("SELECT COUNT(*) FROM load_revisions WHERE run_key = 'r2'").fetchone()[0] == 0
    assert conn.execute("SELECT DISTINCT run_key FROM fact_production_monthly").fetchall() == [("r2",)]
    assert conn.execute("SELECT COUNT(*) FROM period_totals WHERE run_key = 'r2'").fetchone()[0] == conn.execute("SELECT COUNT(*) FROM period_totals WHERE run_key = 'r1'").fetchone()[0]
    conn.close()


def test_repeating_the_same_run_key_replaces_its_rows(tmp_path: Path, valid_frame) -> None:
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1")
    before = snapshot(conn)
    load_validated_subset(conn, valid_frame, "r1")
    assert snapshot(conn) == before
    conn.close()


# --- revisions (RF06) -------------------------------------------------------------------------------


def shifted(row: pd.Series, year: int, month: int) -> pd.Series:
    """The same row for another month."""
    row = row.copy()
    row["year"], row["month"] = year, month
    row["period_key"], row["period_index"] = year * 100 + month, year * 12 + month - 1
    row["period_end"] = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    return row


def test_revisions_count_changed_disappeared_and_added_rows_of_earlier_periods(tmp_path: Path, valid_frame, fixture_truth: FixtureTruth) -> None:
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1")
    before = previous_load(conn)

    new = valid_frame.copy()
    ix = lambda period: new.index[new["period_key"] == period]  # noqa: E731
    events = Counter()

    new.loc[ix(202001)[0], "oil_m3"] += 1.0; events[202001] += 1                        # changed
    new.loc[ix(202002)[0], "oil_m3"] += 5e-7                                            # inside the tolerance: not counted
    new.loc[ix(202003)[1], "gas_thousand_m3"] += 2e-6; events[202003] += 1              # just over it
    new.loc[ix(202004)[2], "oil_m3"] = float("nan"); events[202004] += 1                # value -> NULL
    new = new.drop(index=ix(202005)[3]); events[202005] += 1                            # disappeared
    well, missing_period = fixture_truth.missing_month_rows[0]
    neighbour = new[(new["well_id"] == well)].iloc[0]
    year, month = divmod(missing_period, 100)
    new = pd.concat([new, shifted(neighbour, year, month).to_frame().T.astype(new.dtypes.to_dict())], ignore_index=True)
    events[missing_period] += 1                                                         # added to an old period
    latest = new[new["period_key"] == 202412].copy()
    appended = pd.DataFrame([shifted(r, 2025, 1) for _, r in latest.iterrows()]).astype(new.dtypes.to_dict())
    new = pd.concat([new, appended], ignore_index=True)                                 # a new month: not a revision

    result = load_validated_subset(conn, new, "r2")
    assert result.revised_rows == 5 == sum(events.values())
    stored = dict(conn.execute("SELECT period_key, rows_changed FROM load_revisions WHERE run_key = 'r2'").fetchall())
    assert stored == dict(events)
    assert (result.rows, result.last_period_key) == (len(new), 202501)
    assert conn.execute("SELECT COUNT(*) FROM raw_monthly_production").fetchone()[0] == len(new)
    assert before is not None and before.last_period_key == 202412
    assert previous_load(conn).last_period_key == 202501
    assert conn.execute("SELECT is_last_published FROM dim_calendar WHERE period_key = 202501").fetchone() == (1,)
    conn.close()


def test_a_first_load_has_no_revisions(empty, valid_frame) -> None:
    assert load_validated_subset(empty, valid_frame, "r1").revised_rows == 0
    assert empty.execute("SELECT COUNT(*) FROM load_revisions").fetchone()[0] == 0


# --- all or nothing ---------------------------------------------------------------------------------


def test_a_failing_control_aborts_the_whole_load(tmp_path: Path, valid_frame, monkeypatch) -> None:
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1")
    before = snapshot(conn)

    sql_copy = tmp_path / "sql"
    shutil.copytree(warehouse.SQL_DIR, sql_copy)
    (sql_copy / "checks" / "production" / "chk_always_fails.sql").write_text("SELECT 1 AS broken, 'boom' AS why;\n", encoding="utf-8")
    monkeypatch.setattr(warehouse, "SQL_DIR", sql_copy)
    smaller = valid_frame[valid_frame["period_key"] <= 202406].copy()
    with pytest.raises(CheckFailedError, match="chk_always_fails") as info:
        load_validated_subset(conn, smaller, "r2")
    assert [(c.check_id, c.violations, c.sample) for c in info.value.checks if c.violations] == [("chk_always_fails", 1, [(1, "boom")])]
    assert not conn.in_transaction
    assert snapshot(conn) == before  # raw, staging, marts, revisions and totals are all as they were
    conn.close()


def test_an_empty_subset_aborts_the_load_and_keeps_the_previous_one(tmp_path: Path, valid_frame) -> None:
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1")
    before = snapshot(conn)
    with pytest.raises(warehouse.EmptySubsetError, match="r2"):
        load_validated_subset(conn, valid_frame.iloc[0:0].copy(), "r2")
    assert not conn.in_transaction
    assert snapshot(conn) == before  # nothing was wiped: the empty load never committed
    conn.close()


def test_a_failing_first_load_leaves_an_empty_warehouse(tmp_path: Path, valid_frame, monkeypatch) -> None:
    conn = connect(tmp_path / "w.sqlite")
    sql_copy = tmp_path / "sql"
    shutil.copytree(warehouse.SQL_DIR, sql_copy)
    (sql_copy / "checks" / "production" / "chk_always_fails.sql").write_text("SELECT 1;\n", encoding="utf-8")
    monkeypatch.setattr(warehouse, "SQL_DIR", sql_copy)
    with pytest.raises(CheckFailedError):
        load_validated_subset(conn, valid_frame, "r1")
    assert not table_exists(conn, "dim_well") and not table_exists(conn, "raw_monthly_production")
    assert previous_load(conn) is None
    conn.close()


def test_duplicate_keys_abort_the_load_and_keep_the_previous_one(tmp_path: Path, valid_frame) -> None:
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1")
    before = snapshot(conn)
    broken = pd.concat([valid_frame, valid_frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(sqlite3.IntegrityError):
        load_validated_subset(conn, broken, "r2")
    assert not conn.in_transaction
    assert snapshot(conn) == before
    conn.close()


# --- previous_load ----------------------------------------------------------------------------------


def test_previous_load_is_none_on_a_new_warehouse(empty) -> None:
    assert previous_load(empty) is None
    apply_schema(empty)
    assert previous_load(empty) is None


def test_previous_load_describes_what_the_warehouse_holds(loaded, valid_frame, valid_report) -> None:
    conn, _ = loaded
    previous = previous_load(conn)
    assert isinstance(previous, PreviousLoad)
    assert (previous.rows_subset, previous.wells_subset, previous.last_period_key) == (
        valid_report.rows_subset, valid_report.wells_subset, valid_report.last_period_key,
    )
    totals = previous.period_totals
    assert list(totals.columns) == ["period_key", "oil_m3", "gas_thousand_m3"]
    expected = valid_frame.groupby("period_key")[["oil_m3", "gas_thousand_m3"]].sum().reset_index()
    assert totals["period_key"].tolist() == expected["period_key"].tolist()
    assert totals["oil_m3"].tolist() == pytest.approx(expected["oil_m3"].tolist())
    assert totals["gas_thousand_m3"].tolist() == pytest.approx(expected["gas_thousand_m3"].tolist())


def test_previous_load_feeds_the_next_validation(loaded, fixture_csv: Path, malformed) -> None:
    conn, _ = loaded
    previous = previous_load(conn)
    again, frame = validate_file(fixture_csv, CFG, previous, "r2", TODAY)
    assert not again.blocking_failed and frame is not None
    assert all(r.passed for r in again.results if r.rule_id in ("V09", "V10", "V20"))
    truncated, _ = validate_file(malformed("truncated"), CFG, previous, "r3", TODAY)
    assert not next(r for r in truncated.results if r.rule_id == "V09").passed


# --- consistency between the validation and the SQL corrections (AC06) ------------------------------


@pytest.fixture(scope="module")
def awkward(tmp_path_factory, fixture_csv: Path, fixture_truth: FixtureTruth):
    """The valid fixture with the cases the plain fixture lacks: a volume ceiling, a well with a
    fixed attribute that changes, and a well with coordinates outside the basin."""
    frame = read_source_csv(fixture_csv)
    wells = sorted(fixture_truth.wells)
    scoped = (frame["cuenca"] == "NEUQUINA") & (frame["tipo_de_recurso"] == "NO CONVENCIONAL")
    frame.loc[frame.index[scoped][0], "prod_pet"] = "31000"
    frame.loc[frame.index[scoped][-1], "prod_gas"] = "61000"
    frame.loc[frame.index[frame["idpozo"] == str(wells[4])][0], "provincia"] = "Mendoza X"
    frame.loc[frame["idpozo"] == str(wells[1]), "coordenaday"] = "-10.0"
    path = tmp_path_factory.mktemp("awkward") / "awkward.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    report, validated = validate_file(path, CFG, None, "awk", TODAY)
    conn = connect(tmp_path_factory.mktemp("awk_wh") / "production.sqlite")
    load_validated_subset(conn, validated, "awk")
    yield report, conn
    conn.close()


def result_of(report, rule_id):
    return next(r for r in report.results if r.rule_id == rule_id)


def count(conn, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def test_stg_flags_match_the_validation_row_counts(awkward) -> None:
    report, conn = awkward
    flagged = lambda flag: count(conn, "SELECT COUNT(*) FROM stg_monthly_production WHERE ';' || quality_flags || ';' LIKE ?", f"%;{flag};%")  # noqa: E731
    assert flagged("NEG_VOLUME") == result_of(report, "V12").rows_affected == 1
    assert flagged("TEF_GT_DAYS") == result_of(report, "V13").rows_affected == 1
    assert flagged("TEF_ZERO_WITH_PROD") == result_of(report, "V14").rows_affected == 2
    assert flagged("VOLUME_CEILING") == result_of(report, "V15").rows_affected == 2


def test_dim_well_flags_match_the_validation_well_counts(awkward) -> None:
    report, conn = awkward
    flagged = lambda *flags: count(conn, "SELECT COUNT(*) FROM dim_well WHERE " + " OR ".join(["quality_flags LIKE ?"] * len(flags)), *[f"%{f}%" for f in flags])  # noqa: E731
    assert flagged("COORDS_SWAPPED", "COORDS_OUTSIDE") == result_of(report, "V16").wells_affected == 2
    assert flagged("COORDS_SWAPPED") == 1 and flagged("COORDS_OUTSIDE") == 1
    assert flagged("DEPTH_INVALID") == result_of(report, "V17").wells_affected == 2
    assert flagged("FIXED_ATTR_CHANGED") == result_of(report, "V18").wells_affected == 1


def test_outside_coordinates_become_null_and_the_last_province_is_kept(awkward, fixture_truth: FixtureTruth) -> None:
    _, conn = awkward
    wells = sorted(fixture_truth.wells)
    assert conn.execute("SELECT lon, lat, quality_flags FROM dim_well WHERE well_key = ?", (wells[1],)).fetchone() == (None, None, "COORDS_OUTSIDE")
    province, flags = conn.execute("SELECT province, quality_flags FROM dim_well WHERE well_key = ?", (wells[4],)).fetchone()
    assert flags == "FIXED_ATTR_CHANGED" and province != "Mendoza X"  # the edit was on the well's first row


def test_the_ceilings_come_from_the_configuration(tmp_path: Path, valid_frame) -> None:
    low = replace(CFG, validation=replace(CFG.validation, oil_ceiling_m3=100.0))
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, valid_frame, "r1", cfg=low)
    flagged = count(conn, "SELECT COUNT(*) FROM stg_monthly_production WHERE quality_flags LIKE '%VOLUME_CEILING%'")
    assert flagged == int(((valid_frame["oil_m3"] > 100.0) | (valid_frame["gas_thousand_m3"] > 60000.0)).sum()) > 0
    conn.close()


def test_staging_changes_only_the_values_the_corrections_name(loaded) -> None:
    conn, _ = loaded
    differing = lambda column: count(  # noqa: E731
        conn,
        f"SELECT COUNT(*) FROM stg_monthly_production AS s JOIN raw_monthly_production AS r "
        f"ON r.well_id = s.well_id AND r.period_key = s.period_key WHERE s.{column} IS NOT r.{column}",
    )
    assert differing("gas_thousand_m3") == 1  # the negative one
    assert differing("effective_days") == 1  # the one above the days of the month
    assert differing("oil_m3") == 0 and differing("water_m3") == 0
    assert differing("lon") == 0 and differing("depth_m") == 0  # coordinates and depth are corrected in dim_well


def test_dim_company_takes_the_name_from_the_latest_row(tmp_path: Path, valid_frame) -> None:
    renamed = valid_frame.copy()
    code = renamed["company_code"].iloc[0]
    late = (renamed["company_code"] == code) & (renamed["period_key"] >= 202401)
    renamed.loc[late, "company_name"] = "RENAMED OPERATOR"
    conn = connect(tmp_path / "w.sqlite")
    load_validated_subset(conn, renamed, "r1")
    assert conn.execute("SELECT company_name FROM dim_company WHERE company_key = ?", (code,)).fetchone() == ("RENAMED OPERATOR",)
    assert count(conn, "SELECT COUNT(*) FROM dim_company") == renamed["company_code"].nunique()
    conn.close()
