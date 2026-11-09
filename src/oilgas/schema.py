"""Data contract of the Secretaria de Energia per-well production file.

``SOURCE_COLUMNS`` is the published header (40 columns, in order). ``USED_COLUMNS`` maps the columns
the project reads to ``(english_name, kind)``; the other six are never read. ``kind`` is how
``validate.py`` converts the text: ``int``, ``float``, ``text``, ``flag`` (``t``/``f``),
``timestamp`` or ``date``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SOURCE_COLUMNS: tuple[str, ...] = (
    "idempresa", "anio", "mes", "idpozo", "prod_pet", "prod_gas", "prod_agua",
    "iny_agua", "iny_gas", "iny_co2", "iny_otro", "tef", "vida_util",
    "tipoextraccion", "tipoestado", "tipopozo", "observaciones", "fechaingreso",
    "rectificado", "habilitado", "idusuario", "empresa", "sigla", "formprod",
    "profundidad", "formacion", "idareapermisoconcesion", "areapermisoconcesion",
    "idareayacimiento", "areayacimiento", "cuenca", "provincia", "coordenadax",
    "coordenaday", "tipo_de_recurso", "proyecto", "clasificacion", "subclasificacion",
    "sub_tipo_recurso", "fecha_data",
)

UNUSED_COLUMNS: tuple[str, ...] = ("iny_agua", "iny_gas", "iny_co2", "iny_otro", "vida_util", "idusuario")

# source column -> (english name, kind)
USED_COLUMNS: dict[str, tuple[str, str]] = {
    "idempresa": ("company_code", "text"),
    "empresa": ("company_name", "text"),
    "anio": ("year", "int"),
    "mes": ("month", "int"),
    "idpozo": ("well_id", "int"),
    "sigla": ("well_code", "text"),
    "prod_pet": ("oil_m3", "float"),
    "prod_gas": ("gas_thousand_m3", "float"),
    "prod_agua": ("water_m3", "float"),
    "tef": ("effective_days", "float"),
    "tipoextraccion": ("extraction_method", "text"),
    "tipoestado": ("well_status", "text"),
    "tipopozo": ("well_type", "text"),
    "observaciones": ("remarks", "text"),
    "fechaingreso": ("loaded_at", "timestamp"),
    "rectificado": ("is_rectified", "flag"),
    "habilitado": ("is_enabled", "flag"),
    "formprod": ("formation_code", "text"),
    "formacion": ("formation_name", "text"),
    "profundidad": ("depth_m", "float"),
    "idareapermisoconcesion": ("concession_code", "text"),
    "areapermisoconcesion": ("concession_name", "text"),
    "idareayacimiento": ("field_code", "text"),
    "areayacimiento": ("field_name", "text"),
    "cuenca": ("basin", "text"),
    "provincia": ("province", "text"),
    "coordenadax": ("lon", "float"),
    "coordenaday": ("lat", "float"),
    "tipo_de_recurso": ("resource_type", "text"),
    "sub_tipo_recurso": ("sub_resource_type", "text"),
    "proyecto": ("project", "text"),
    "clasificacion": ("classification", "text"),
    "subclasificacion": ("subclassification", "text"),
    "fecha_data": ("period_end", "date"),
}


def read_source_csv(path: Path) -> pd.DataFrame:
    """Read the file as published: UTF-8 with or without BOM, every value as text.

    Empty cells become missing values. Nothing is converted here, so the validation sees each value
    exactly as it arrives and can count what does not convert. Raises ``UnicodeDecodeError`` if the
    bytes are not UTF-8 (rule V01).
    """
    return pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
        na_values=[""],
    )


def period_index_of(year, month):
    """Month index ``year * 12 + month - 1``: the arithmetic of months (D03). Works on numbers and arrays."""
    return year * 12 + month - 1


def period_index_of_key(period_key):
    """Month index of a ``period_key`` written ``AAAAMM`` (``period_index_of`` of its year and month)."""
    return period_index_of(period_key // 100, period_key % 100)
