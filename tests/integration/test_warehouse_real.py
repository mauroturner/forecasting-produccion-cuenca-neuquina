"""AC05 and AC06 on the real publication (marked real_data): the load, the controls and the corrections."""

from __future__ import annotations

from datetime import date

import pytest

from oilgas.config import load_config
from oilgas.validate import validate_file
from oilgas.warehouse import connect, load_validated_subset, previous_load, run_checks
from tests.conftest import REAL_CSV

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    cfg = load_config()
    report, frame = validate_file(REAL_CSV, cfg, None, "real", date(2026, 11, 9))
    conn = connect(tmp_path_factory.mktemp("real") / "production.sqlite")
    result = load_validated_subset(conn, frame, "real", cfg=cfg)
    yield report, conn, result
    conn.close()


def one(conn, sql: str, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_the_real_load_matches_the_validation_and_every_control_passes(real) -> None:
    report, conn, result = real
    assert (result.rows, result.wells, result.last_period_key) == (413_865, 4_937, 202609)
    assert result.revised_rows == 0
    assert all(c.violations == 0 for c in run_checks(conn, "production")) and len(result.checks) == 10
    assert one(conn, "SELECT COUNT(*) FROM stg_monthly_production") == report.rows_subset
    assert one(conn, "SELECT COUNT(*) FROM dim_well") == report.wells_subset
    assert one(conn, "SELECT COUNT(*) FROM fact_production_monthly") == report.rows_subset


def test_the_real_corrections_match_the_validation_counts(real) -> None:
    report, conn, _ = real
    by_id = {r.rule_id: r for r in report.results}
    flagged = lambda flag: one(conn, "SELECT COUNT(*) FROM stg_monthly_production WHERE ';' || quality_flags || ';' LIKE ?", f"%;{flag};%")  # noqa: E731
    assert flagged("NEG_VOLUME") == by_id["V12"].rows_affected == 2
    assert flagged("TEF_GT_DAYS") == by_id["V13"].rows_affected == 70
    assert flagged("TEF_ZERO_WITH_PROD") == by_id["V14"].rows_affected == 384
    assert flagged("VOLUME_CEILING") == by_id["V15"].rows_affected == 0
    wells = lambda *flags: one(conn, "SELECT COUNT(*) FROM dim_well WHERE " + " OR ".join(["quality_flags LIKE ?"] * len(flags)), *[f"%{f}%" for f in flags])  # noqa: E731
    assert wells("COORDS_SWAPPED", "COORDS_OUTSIDE") == by_id["V16"].wells_affected == 1
    assert wells("DEPTH_INVALID") == by_id["V17"].wells_affected == 176
    assert wells("FIXED_ATTR_CHANGED") == by_id["V18"].wells_affected == 0


def test_reloading_the_real_publication_changes_nothing_and_has_no_revisions(real) -> None:
    report, conn, _ = real
    before = conn.execute("SELECT COUNT(*), SUM(oil_m3), SUM(gas_thousand_m3) FROM stg_monthly_production").fetchone()
    previous = previous_load(conn)
    assert (previous.rows_subset, previous.wells_subset, previous.last_period_key) == (413_865, 4_937, 202609)
    again, frame = validate_file(REAL_CSV, load_config(), previous, "real2", date(2026, 11, 9))
    assert not again.blocking_failed and all(r.passed for r in again.results if r.rule_id in ("V09", "V10", "V20"))
    result = load_validated_subset(conn, frame, "real2")
    assert result.revised_rows == 0
    assert conn.execute("SELECT COUNT(*), SUM(oil_m3), SUM(gas_thousand_m3) FROM stg_monthly_production").fetchone() == before
