"""The contract against the real publication (marked real_data; skipped when it is not downloaded)."""

from __future__ import annotations

import pytest

from oilgas.schema import SOURCE_COLUMNS, USED_COLUMNS, read_source_csv
from tests.conftest import REAL_CSV

pytestmark = pytest.mark.real_data


def test_real_header_is_the_contract() -> None:
    with open(REAL_CSV, encoding="utf-8-sig") as handle:
        header = handle.readline().rstrip("\n").split(",")
    assert tuple(header) == SOURCE_COLUMNS


def test_real_file_reads_whole_with_the_used_columns_present() -> None:
    df = read_source_csv(REAL_CSV)
    assert df.shape[1] == 40
    assert len(df) > 400_000
    assert set(USED_COLUMNS) <= set(df.columns)
    assert set(df["cuenca"].dropna()) >= {"NEUQUINA"}
    assert set(df["tipo_de_recurso"].dropna()) == {"NO CONVENCIONAL"}
