"""Data contract of the source file: 40 columns, the used subset and the reader (part of AC03)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from oilgas.schema import SOURCE_COLUMNS, UNUSED_COLUMNS, USED_COLUMNS, read_source_csv

PUBLISHED_HEADER = (
    "idempresa,anio,mes,idpozo,prod_pet,prod_gas,prod_agua,iny_agua,iny_gas,iny_co2,iny_otro,tef,"
    "vida_util,tipoextraccion,tipoestado,tipopozo,observaciones,fechaingreso,rectificado,habilitado,"
    "idusuario,empresa,sigla,formprod,profundidad,formacion,idareapermisoconcesion,"
    "areapermisoconcesion,idareayacimiento,areayacimiento,cuenca,provincia,coordenadax,coordenaday,"
    "tipo_de_recurso,proyecto,clasificacion,subclasificacion,sub_tipo_recurso,fecha_data"
)

EXPECTED_NAMES = {
    "idempresa": "company_code", "empresa": "company_name", "anio": "year", "mes": "month",
    "idpozo": "well_id", "sigla": "well_code", "prod_pet": "oil_m3", "prod_gas": "gas_thousand_m3",
    "prod_agua": "water_m3", "tef": "effective_days", "tipoextraccion": "extraction_method",
    "tipoestado": "well_status", "tipopozo": "well_type", "observaciones": "remarks",
    "fechaingreso": "loaded_at", "rectificado": "is_rectified", "habilitado": "is_enabled",
    "formprod": "formation_code", "formacion": "formation_name", "profundidad": "depth_m",
    "idareapermisoconcesion": "concession_code", "areapermisoconcesion": "concession_name",
    "idareayacimiento": "field_code", "areayacimiento": "field_name", "cuenca": "basin",
    "provincia": "province", "coordenadax": "lon", "coordenaday": "lat",
    "tipo_de_recurso": "resource_type", "sub_tipo_recurso": "sub_resource_type",
    "proyecto": "project", "clasificacion": "classification",
    "subclasificacion": "subclassification", "fecha_data": "period_end",
}


def test_source_columns_are_the_forty_published_ones_in_order() -> None:
    assert len(SOURCE_COLUMNS) == 40
    assert ",".join(SOURCE_COLUMNS) == PUBLISHED_HEADER
    assert len(set(SOURCE_COLUMNS)) == 40


def test_used_and_unused_columns_partition_the_source() -> None:
    assert set(USED_COLUMNS) | set(UNUSED_COLUMNS) == set(SOURCE_COLUMNS)
    assert not set(USED_COLUMNS) & set(UNUSED_COLUMNS)
    assert set(UNUSED_COLUMNS) == {"iny_agua", "iny_gas", "iny_co2", "iny_otro", "vida_util", "idusuario"}
    assert len(USED_COLUMNS) == 34


def test_used_columns_are_renamed_to_unique_english_names() -> None:
    names = [english for english, _ in USED_COLUMNS.values()]
    assert len(set(names)) == len(names)
    assert {src: english for src, (english, _) in USED_COLUMNS.items()} == EXPECTED_NAMES


def test_used_columns_declare_a_known_type() -> None:
    kinds = {kind for _, kind in USED_COLUMNS.values()}
    assert kinds <= {"int", "float", "text", "flag", "timestamp", "date"}
    assert USED_COLUMNS["idpozo"][1] == "int"
    assert USED_COLUMNS["prod_pet"][1] == "float"
    assert USED_COLUMNS["rectificado"][1] == "flag"
    assert USED_COLUMNS["fechaingreso"][1] == "timestamp"
    assert USED_COLUMNS["fecha_data"][1] == "date"
    assert USED_COLUMNS["empresa"][1] == "text"


def test_real_sample_is_read_as_published(real_sample_path: Path) -> None:
    df = read_source_csv(real_sample_path)
    assert tuple(df.columns) == SOURCE_COLUMNS  # the BOM does not leak into the first name
    assert len(df) == 1130
    assert df["idpozo"].nunique() == 5
    # every value arrives as text: the validation converts and counts what does not convert
    assert all(pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]) for c in df.columns)
    assert df["anio"].iloc[0] == "2016" and df["mes"].iloc[0] == "1"
    # decimal point and untouched text
    assert df["prod_pet"].iloc[0] == "31.23"
    assert df["fecha_data"].iloc[0] == "2016-01-31"
    # accents survive the UTF-8 decoding
    assert "Extracción Efectiva" in set(df["tipoestado"])
    assert "Petrolífero" in set(df["tipopozo"])
    # empty cells are missing values, not empty strings
    assert df["vida_util"].isna().any()
    for column in ("vida_util", "observaciones"):
        assert (df[column] == "").sum() == 0
    assert set(df["cuenca"]) == {"NEUQUINA"} and set(df["tipo_de_recurso"]) == {"NO CONVENCIONAL"}


def test_read_source_csv_without_bom(tmp_path: Path, real_sample_path: Path) -> None:
    raw = real_sample_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    plain = tmp_path / "plain.csv"
    plain.write_bytes(raw[3:])
    pd.testing.assert_frame_equal(read_source_csv(real_sample_path), read_source_csv(plain))


def test_the_valid_fixture_has_the_published_shape(fixture_csv: Path) -> None:
    assert fixture_csv.read_bytes().startswith(b"\xef\xbb\xbf")
    df = read_source_csv(fixture_csv)
    assert tuple(df.columns) == SOURCE_COLUMNS
    assert len(df) > 2000


def test_period_index_helpers_agree_with_the_calendar() -> None:
    import numpy as np

    from oilgas.schema import period_index_of, period_index_of_key

    assert period_index_of(2026, 9) == 2026 * 12 + 8
    assert period_index_of_key(202609) == period_index_of(2026, 9)
    assert period_index_of_key(200601) == 2006 * 12  # January is the first month of its year
    assert period_index_of(2026, 1) - period_index_of(2025, 12) == 1
    keys = pd.Index([200601, 202612])  # works on the arrays the validation uses
    assert list(period_index_of_key(keys)) == [2006 * 12, 2026 * 12 + 11]
    assert list(period_index_of(np.array([2006, 2026]), np.array([1, 12]))) == [2006 * 12, 2026 * 12 + 11]
