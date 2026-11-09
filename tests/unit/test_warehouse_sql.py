"""The SQL runner: connection settings, statement splitting, parameters, the schema, run records."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from oilgas import warehouse
from oilgas.validate import Severity
from oilgas.warehouse import (
    BUSY_TIMEOUT_MS,
    SchemaDriftError,
    apply_schema,
    connect,
    record_run,
    record_validation_results,
    run_checks,
    run_sql_file,
    split_statements,
)

CORE_TABLES = {
    "raw_monthly_production", "stg_monthly_production", "pipeline_runs", "validation_results",
    "period_totals", "load_revisions",
}
MODEL_TABLES = {
    "model_fit", "model_forecast", "model_fitted_curve", "model_backtest_metrics", "model_summary",
    "model_selection",
}


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.fixture()
def conn(tmp_path: Path):
    connection = connect(tmp_path / "w" / "production.sqlite")
    yield connection
    connection.close()


# --- connect ----------------------------------------------------------------------------------------


def test_connect_creates_the_folder_and_sets_the_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "production.sqlite"
    connection = connect(path)
    try:
        assert path.exists()
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.isolation_level is None  # autocommit: transactions are explicit
    finally:
        connection.close()


def test_connect_autocommits_outside_a_transaction(tmp_path: Path) -> None:
    path = tmp_path / "w.sqlite"
    first = connect(path)
    first.execute("CREATE TABLE t (x INTEGER)")
    first.execute("INSERT INTO t VALUES (1)")
    assert not first.in_transaction
    second = connect(path)
    assert second.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    first.close()
    second.close()


# --- split_statements -------------------------------------------------------------------------------


def test_split_statements_separates_on_semicolons() -> None:
    assert split_statements("SELECT 1;\nSELECT 2;\n") == ["SELECT 1;", "SELECT 2;"]


def test_split_statements_keeps_semicolons_inside_strings() -> None:
    sql = "INSERT INTO t VALUES ('a;b');\nSELECT ';';"
    assert split_statements(sql) == ["INSERT INTO t VALUES ('a;b');", "SELECT ';';"]


def test_split_statements_ignores_semicolons_in_comments() -> None:
    sql = "-- first; second\nSELECT 1; /* a; b */\nSELECT 2;"
    statements = split_statements(sql)
    assert len(statements) == 2
    assert "SELECT 1;" in statements[0] and statements[1].endswith("SELECT 2;")


def test_split_statements_drops_comment_only_remainders() -> None:
    assert split_statements("SELECT 1;\n-- nothing else\n") == ["SELECT 1;"]
    assert split_statements("-- only a comment\n/* and another */") == []
    assert split_statements("") == [] and split_statements("  \n ; \n") == []


def test_split_statements_keeps_a_last_statement_without_semicolon() -> None:
    assert split_statements("SELECT 1;\nSELECT 2") == ["SELECT 1;", "SELECT 2"]


def test_split_statements_keeps_a_trigger_body_whole() -> None:
    sql = (
        "CREATE TRIGGER trg AFTER INSERT ON t BEGIN\n  UPDATE t SET x = 1;\n  UPDATE t SET x = 2;\nEND;\nSELECT 1;"
    )
    statements = split_statements(sql)
    assert len(statements) == 2 and statements[0].startswith("CREATE TRIGGER") and statements[0].endswith("END;")


# --- run_sql_file -----------------------------------------------------------------------------------


def test_run_sql_file_runs_every_statement_with_named_parameters(conn, tmp_path: Path) -> None:
    sql = tmp_path / "a.sql"
    sql.write_text(
        "-- creates and fills a table\nCREATE TABLE t (name TEXT, n INTEGER);\n"
        "INSERT INTO t VALUES (:name, :n);\nINSERT INTO t VALUES ('b;c', 2);\n",
        encoding="utf-8",
    )
    run_sql_file(conn, sql, {"name": "a", "n": 1, "unused": "ignored"})
    assert conn.execute("SELECT name, n FROM t ORDER BY n").fetchall() == [("a", 1), ("b;c", 2)]


def test_run_sql_file_reports_a_missing_parameter(conn, tmp_path: Path) -> None:
    sql = tmp_path / "a.sql"
    sql.write_text("CREATE TABLE t (n INTEGER);\nINSERT INTO t VALUES (:n);\n", encoding="utf-8")
    with pytest.raises(sqlite3.ProgrammingError):
        run_sql_file(conn, sql, {})


def test_run_sql_file_never_commits_an_open_transaction(conn, tmp_path: Path) -> None:
    sql = tmp_path / "a.sql"
    sql.write_text("CREATE TABLE t (n INTEGER);\nINSERT INTO t VALUES (1);\n", encoding="utf-8")
    conn.execute("BEGIN IMMEDIATE")
    run_sql_file(conn, sql)
    assert conn.in_transaction
    conn.execute("ROLLBACK")
    assert "t" not in tables(conn)  # executescript() would have committed it first


def test_run_sql_file_stops_at_the_first_failing_statement(conn, tmp_path: Path) -> None:
    sql = tmp_path / "a.sql"
    sql.write_text("CREATE TABLE t (n INTEGER);\nINSERT INTO nope VALUES (1);\nINSERT INTO t VALUES (2);\n", encoding="utf-8")
    conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError, match="nope"):
        run_sql_file(conn, sql)
    conn.execute("ROLLBACK")
    assert "t" not in tables(conn)


# --- schema -----------------------------------------------------------------------------------------


def test_apply_schema_creates_the_core_and_model_tables(conn) -> None:
    apply_schema(conn)
    assert CORE_TABLES | MODEL_TABLES <= tables(conn)


def test_apply_schema_is_idempotent_and_keeps_the_data(conn) -> None:
    apply_schema(conn)
    record_run(conn, {"run_key": "r1", "status": "ok", "rows_subset": 5})
    apply_schema(conn)
    assert conn.execute("SELECT run_key, status, rows_subset FROM pipeline_runs").fetchall() == [("r1", "ok", 5)]


def test_the_raw_table_has_the_columns_of_the_validated_frame(conn, valid_frame) -> None:
    apply_schema(conn)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(raw_monthly_production)")]
    assert sorted(columns) == sorted(valid_frame.columns)
    key = [r[1] for r in conn.execute("PRAGMA table_info(raw_monthly_production)") if r[5]]
    assert sorted(key) == ["period_key", "well_id"]


# --- run records ------------------------------------------------------------------------------------


def test_record_run_inserts_and_then_updates_only_what_it_is_given(conn) -> None:
    apply_schema(conn)
    record_run(conn, {"run_key": "r1", "started_at": "2026-11-09T10:00:00+00:00", "status": "running", "source_size": 123})
    record_run(conn, {"run_key": "r1", "finished_at": "2026-11-09T10:05:00+00:00", "status": "ok", "message": "done"})
    row = conn.execute("SELECT * FROM pipeline_runs").fetchone()
    columns = [d[0] for d in conn.execute("SELECT * FROM pipeline_runs").description]
    record = dict(zip(columns, row, strict=True))
    assert record["started_at"] == "2026-11-09T10:00:00+00:00"  # untouched by the second call
    assert record["source_size"] == 123
    assert (record["finished_at"], record["status"], record["message"]) == ("2026-11-09T10:05:00+00:00", "ok", "done")
    assert conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 1


def test_record_run_rejects_unknown_columns_and_a_missing_key(conn) -> None:
    apply_schema(conn)
    with pytest.raises(ValueError, match="colour"):
        record_run(conn, {"run_key": "r1", "colour": "red"})
    with pytest.raises(ValueError, match="run_key"):
        record_run(conn, {"status": "ok"})
    assert conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 0


def test_record_validation_results_stores_one_row_per_rule_and_replaces_a_rerun(conn, valid_report) -> None:
    apply_schema(conn)
    record_validation_results(conn, valid_report)
    record_validation_results(conn, valid_report)
    rows = conn.execute(
        "SELECT rule_id, severity, passed, rows_affected, wells_affected, examples_json FROM validation_results "
        "WHERE run_key = ? ORDER BY rule_id", (valid_report.run_key,)
    ).fetchall()
    assert [r[0] for r in rows] == sorted(r.rule_id for r in valid_report.results)
    v12 = next(r for r in rows if r[0] == "V12")
    assert v12[1:5] == ("advertencia", 0, 1, 1)
    assert json.loads(v12[5])[0]["value"] == -12.5
    assert next(r for r in rows if r[0] == "V01")[1:3] == ("bloqueante", 1)
    assert next(r for r in rows if r[0] == "I01")[1] == "informativa"
    assert all(r.severity in Severity for r in valid_report.results)


# --- checks -----------------------------------------------------------------------------------------


def test_run_checks_rejects_an_unknown_group(conn) -> None:
    apply_schema(conn)
    with pytest.raises(ValueError, match="nonsense"):
        run_checks(conn, "nonsense")


def test_model_checks_are_empty_until_the_model_defines_them(conn) -> None:
    apply_schema(conn)
    assert run_checks(conn, "model") == [] or all(c.violations == 0 for c in run_checks(conn, "model"))


def test_every_production_check_exists_and_is_named_after_its_file() -> None:
    names = sorted(p.stem for p in (warehouse.SQL_DIR / "checks" / "production").glob("chk_*.sql"))
    assert names == [
        "chk_dim_calendar_contiguous", "chk_dim_company_unique", "chk_dim_well_unique",
        "chk_fact_production_fk_calendar", "chk_fact_production_fk_company", "chk_fact_production_fk_well",
        "chk_stg_effective_days", "chk_stg_nonnegative", "chk_stg_period_range", "chk_stg_unique_key",
    ]


def test_each_check_returns_the_rows_that_break_its_rule(conn) -> None:
    """Hand-made tables with exactly one kind of problem each (no primary keys, so duplicates can exist)."""
    for statement in [
        "CREATE TABLE stg_monthly_production (well_id, period_key, period_index, year, month, days_in_month, "
        "oil_m3, gas_thousand_m3, water_m3, effective_days)",
        "CREATE TABLE dim_well (well_key)",
        "CREATE TABLE dim_company (company_key)",
        "CREATE TABLE dim_calendar (period_key, period_index)",
        "CREATE TABLE fact_production_monthly (well_key, period_key, company_key)",
    ]:
        conn.execute(statement)
    conn.executemany(
        "INSERT INTO stg_monthly_production VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 202001, 24240, 2020, 1, 31, 10.0, 5.0, 1.0, 31.0),   # a good row
            (1, 202001, 24240, 2020, 1, 31, 10.0, 5.0, 1.0, 31.0),   # same key again
            (2, 202013, 24252, 2020, 13, 31, 1.0, 1.0, 1.0, 10.0),   # month 13
            (3, 202002, 24241, 2020, 2, 29, -1.0, 1.0, 1.0, 10.0),   # negative oil
            (4, 202003, 24242, 2020, 3, 31, 1.0, 1.0, 1.0, 45.5),    # tef above the days
        ],
    )
    conn.executemany("INSERT INTO dim_well VALUES (?)", [(1,), (7,), (7,)])
    conn.executemany("INSERT INTO dim_company VALUES (?)", [("A",), ("A",), (None,), ("B",)])
    conn.executemany("INSERT INTO dim_calendar VALUES (?, ?)", [(202001, 1), (202002, 2), (202004, 4)])
    conn.executemany(
        "INSERT INTO fact_production_monthly VALUES (?, ?, ?)",
        [(1, 202001, "A"), (9, 202001, "A"), (1, 202001, "Z"), (1, 209912, None)],
    )
    found = {c.check_id: c for c in run_checks(conn, "production")}
    assert {k: v.violations for k, v in found.items()} == {
        "chk_stg_unique_key": 1,
        "chk_stg_period_range": 1,
        "chk_stg_nonnegative": 1,
        "chk_stg_effective_days": 1,
        "chk_dim_well_unique": 1,
        "chk_dim_company_unique": 2,
        "chk_dim_calendar_contiguous": 1,
        "chk_fact_production_fk_well": 1,
        "chk_fact_production_fk_company": 1,
        "chk_fact_production_fk_calendar": 1,
    }
    assert found["chk_stg_unique_key"].sample == [(1, 202001, 2)]
    assert found["chk_fact_production_fk_well"].sample == [(9, 202001)]
    assert found["chk_dim_calendar_contiguous"].sample == [(2,)]


# --- hardening (H1): busy timeout and schema drift ------------------------------------------------------


def test_connect_waits_for_a_lock_instead_of_failing_at_once(tmp_path: Path) -> None:
    path = tmp_path / "w.sqlite"
    holder = connect(path)
    assert holder.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS >= 30_000
    holder.execute("CREATE TABLE t (x INTEGER)")
    holder.execute("BEGIN IMMEDIATE")  # a run holds the write lock
    outcome: dict[str, object] = {}

    def overlapping_run() -> None:  # a second run, in its own thread and connection
        waiter = connect(path)
        started = time.perf_counter()
        try:
            waiter.execute("BEGIN IMMEDIATE")
            outcome["waited"] = time.perf_counter() - started
            waiter.execute("COMMIT")
        except sqlite3.OperationalError as error:
            outcome["error"] = error
        finally:
            waiter.close()

    thread = threading.Thread(target=overlapping_run)
    thread.start()
    time.sleep(0.6)
    holder.execute("COMMIT")
    thread.join(timeout=10)
    holder.close()
    assert "error" not in outcome  # it did not fail with 'database is locked'
    assert outcome["waited"] >= 0.4  # it waited for the first run


def test_a_table_with_an_extra_column_is_reported_as_schema_drift(conn) -> None:
    apply_schema(conn)
    conn.execute("ALTER TABLE model_fit ADD COLUMN stray TEXT")
    with pytest.raises(SchemaDriftError) as info:
        apply_schema(conn)
    assert info.value.table == "model_fit" and info.value.unexpected == ("stray",) and info.value.missing == ()
    assert "model_fit" in str(info.value) and "stray" in str(info.value) and "002_model.sql" in str(info.value)


def test_a_table_with_a_renamed_column_names_the_missing_and_the_unexpected_ones(conn) -> None:
    apply_schema(conn)
    conn.execute("ALTER TABLE model_forecast RENAME COLUMN p10 TO p_ten")
    with pytest.raises(SchemaDriftError) as info:
        apply_schema(conn)
    assert (info.value.table, info.value.missing, info.value.unexpected) == ("model_forecast", ("p10",), ("p_ten",))


def test_a_column_of_another_declared_type_is_schema_drift(conn) -> None:
    apply_schema(conn)
    conn.execute("DROP TABLE period_totals")
    conn.execute("CREATE TABLE period_totals (run_key TEXT, period_key TEXT, oil_m3 REAL, gas_thousand_m3 REAL, rows INTEGER)")
    with pytest.raises(SchemaDriftError, match="period_key") as info:
        apply_schema(conn)
    assert info.value.table == "period_totals" and info.value.retyped == ("period_key",)


def test_a_matching_schema_and_a_missing_table_are_not_drift(conn) -> None:
    apply_schema(conn)
    conn.execute("DROP TABLE model_selection")  # a table that does not exist yet is simply created
    apply_schema(conn)
    assert "model_selection" in tables(conn)
