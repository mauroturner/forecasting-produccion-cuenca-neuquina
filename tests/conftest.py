"""Shared fixtures and the automatic skipping of the real_data and docker marks."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from oilgas.config import load_config
from oilgas.validate import validate_file
from tests.fixtures.make_fixture import FixtureTruth, make_fixture, make_malformed

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_CSV = PROJECT_ROOT / "data" / "raw" / "produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv"
REAL_SAMPLE = PROJECT_ROOT / "tests" / "fixtures" / "real_sample.csv"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, instead of failing, the tests whose external requirement is missing."""
    skips = {
        "real_data": (not REAL_CSV.exists(), "the real publication is not in data/raw/"),
        "docker": (shutil.which("docker") is None, "docker is not installed"),
    }
    for item in items:
        for mark, (missing, reason) in skips.items():
            if mark in item.keywords and missing:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def real_sample_path() -> Path:
    return REAL_SAMPLE


@pytest.fixture(scope="session")
def fixture_truth(tmp_path_factory: pytest.TempPathFactory) -> FixtureTruth:
    """The valid synthetic publication (about 60 wells, known curves) and what it contains."""
    out = tmp_path_factory.mktemp("fixture") / "valid.csv"
    return make_fixture(out, n_wells=60, first=(2018, 1), last=(2024, 12), seed=0)


@pytest.fixture(scope="session")
def fixture_csv(fixture_truth: FixtureTruth) -> Path:
    return fixture_truth.path


@pytest.fixture()
def malformed(fixture_csv: Path, tmp_path: Path) -> Callable[[str], Path]:
    """Factory: malformed(kind) -> path of the valid fixture damaged in the given way."""

    def build(kind: str) -> Path:
        return make_malformed(fixture_csv, kind, tmp_path / f"{kind}.csv")

    return build


@pytest.fixture(scope="session")
def valid_outcome(fixture_csv: Path):
    """(report, frame) of validating the valid fixture on 2025-01-15 as run 'r1'."""
    return validate_file(fixture_csv, load_config(), None, "r1", date(2025, 1, 15))


@pytest.fixture(scope="session")
def valid_report(valid_outcome):
    return valid_outcome[0]


@pytest.fixture(scope="session")
def valid_frame(valid_outcome):
    return valid_outcome[1]


@pytest.fixture(scope="session")
def warehouse_path(tmp_path_factory: pytest.TempPathFactory, valid_frame) -> Path:
    """A warehouse file with the valid fixture loaded as r1 (tests must not write to it)."""
    from oilgas.warehouse import connect, load_validated_subset

    path = tmp_path_factory.mktemp("session_wh") / "production.sqlite"
    conn = connect(path)
    load_validated_subset(conn, valid_frame, "r1")
    conn.close()
    return path


@pytest.fixture(scope="session")
def warehouse_conn(warehouse_path: Path):
    from oilgas.warehouse import connect

    conn = connect(warehouse_path)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def fixture_panel(warehouse_conn):
    """The dense series panel of the valid fixture (60 wells, 2018-01 to 2024-12)."""
    from oilgas.series import build_panel

    return build_panel(warehouse_conn)


@pytest.fixture(scope="session")
def modeled_warehouse(tmp_path_factory: pytest.TempPathFactory, warehouse_path: Path, valid_report) -> Path:
    """The fixture warehouse after the backtest and the forecast, with its run and validation recorded as 'r1'.

    Shared by the whole session and read-only: a test that writes (the export builds marts) copies it first.
    """
    from oilgas.backtest import run_backtest
    from oilgas.forecast import run_production_forecast
    from oilgas.warehouse import connect, record_run, record_validation_results
    from tests.fixtures.modeling import RunCtx, small_cfg

    root = tmp_path_factory.mktemp("modeled")
    path = root / "production.sqlite"
    shutil.copy(warehouse_path, path)
    ctx = RunCtx(small_cfg(path, root / "interim"), "r1")
    run_backtest(ctx)
    run_production_forecast(ctx)
    conn = connect(path)
    record_run(conn, {
        "run_key": "r1", "started_at": "2025-01-15T09:00:00+00:00", "finished_at": "2025-01-15T09:30:00+00:00", "status": "ok",
        "source_url": "http://example.test/resource.csv", "source_etag": '"v1"', "source_last_modified": "Wed, 15 Jan 2025 00:00:00 GMT",
        "source_size": 1234, "source_sha256": "ab" * 32, "last_period_key": valid_report.last_period_key,
        "rows_subset": valid_report.rows_subset, "wells_subset": valid_report.wells_subset, "revised_rows": 0, "message": "ok",
    })
    record_validation_results(conn, valid_report)
    conn.close()
    return path


@pytest.fixture()
def modeled_copy(tmp_path: Path, modeled_warehouse: Path) -> Path:
    """A private copy of the modeled warehouse that a test may write to."""
    path = tmp_path / "production.sqlite"
    shutil.copy(modeled_warehouse, path)
    return path


@pytest.fixture(scope="session")
def star_outputs(tmp_path_factory: pytest.TempPathFactory, modeled_warehouse: Path) -> Path:
    """The Parquet star schema exported once from the modeled warehouse (read-only for the tests)."""
    from oilgas.dashboard.semantic_model import MODEL
    from oilgas.export import export_star_schema
    from oilgas.warehouse import connect

    root = tmp_path_factory.mktemp("star_outputs")
    copy = root / "production.sqlite"
    shutil.copy(modeled_warehouse, copy)
    conn = connect(copy)
    export_star_schema(conn, root / "powerbi", MODEL, "r1", "ab" * 32, "Fuente: Secretaría de Energía (CC BY 4.0).")
    conn.close()
    return root / "powerbi"
