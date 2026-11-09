"""Shared fixtures and the automatic skipping of the real_data and docker marks."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

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
