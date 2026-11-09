"""Pipeline configuration: one TOML file, typed, immutable and checked key by key.

``config/pipeline.toml`` holds every default. A file may start from another one with a top-level
``extends = "<path>"`` (``config/pipeline.quick.toml`` does), and ``load_config`` can merge one more
file of overrides on top. Relative paths in ``[paths]`` are resolved against the project folder.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "pipeline.toml"

ENV_CONFIG = "OILGAS_CONFIG"
ENV_N_WORKERS = "OILGAS_N_WORKERS"


@dataclass(frozen=True)
class SourceConfig:
    mode: str
    url: str
    local_path: str
    package_id: str
    resource_id: str
    chunk_bytes: int
    timeout_s: int


@dataclass(frozen=True)
class ScopeConfig:
    basin: str
    resource_type: str
    first_year: int


@dataclass(frozen=True)
class ValidationConfig:
    min_rows_ratio: float
    min_wells_ratio: float
    max_unparseable_volume_share: float
    last_period_min_ratio: float
    oil_ceiling_m3: float
    gas_ceiling_thousand_m3: float
    basin_lon: tuple[float, ...]
    basin_lat: tuple[float, ...]
    depth_valid_m: tuple[float, ...]
    revision_total_tolerance: float
    revision_min_age_months: int
    freshness_max_days: int


@dataclass(frozen=True)
class ArpsConfig:
    min_post_peak_points: int
    terminal_decline_effective_annual: float
    di_bounds_per_month: tuple[float, ...]
    di_bounds_exp_per_month: tuple[float, ...]
    b_bounds_base: tuple[float, ...]
    b_bounds_sensitivity: tuple[float, ...]
    qi_bound_factor: float
    b_starts_base: tuple[float, ...]
    b_starts_sensitivity: tuple[float, ...]
    loss: str
    f_scale: float
    max_nfev: int


@dataclass(frozen=True)
class BacktestConfig:
    n_eval_origins: int
    n_warmup_origins: int
    eval_horizons: tuple[int, ...]
    max_horizon: int
    all_horizon_methods: tuple[str, ...]
    epsilon_rate: float
    calibration_window_origins: int
    min_calibration_samples: int
    n_workers: int
    well_sample: int
    seed: int


@dataclass(frozen=True)
class MLConfig:
    quantiles: tuple[float, ...]
    retrain_every: int
    train_window_months: int
    max_train_rows: int
    max_iter: int
    learning_rate: float
    max_leaf_nodes: int
    min_samples_leaf: int
    l2_regularization: float
    seed: int
    top_operators: int
    top_formations: int
    top_extraction_methods: int


@dataclass(frozen=True)
class CriteriaConfig:
    share_beats_naive_min: float
    share_beats_horizon: int
    wape_horizons: tuple[int, ...]
    coverage_target: float
    coverage_calibrated: tuple[float, ...]
    coverage_acceptable: tuple[float, ...]
    max_fallback_rate: float


@dataclass(frozen=True)
class PathsConfig:
    raw_dir: Path
    interim_dir: Path
    warehouse: Path
    outputs_dir: Path
    reports_dir: Path
    dashboard_html: Path
    readme: Path


@dataclass(frozen=True)
class PipelineConfig:
    source: SourceConfig
    scope: ScopeConfig
    validation: ValidationConfig
    arps: ArpsConfig
    backtest: BacktestConfig
    ml: MLConfig
    criteria: CriteriaConfig
    paths: PathsConfig


# Keys that must be an ordered (low, high) pair.
_PAIR_KEYS = {
    "validation": ("basin_lon", "basin_lat", "depth_valid_m"),
    "arps": ("di_bounds_per_month", "di_bounds_exp_per_month", "b_bounds_base", "b_bounds_sensitivity"),
    "criteria": ("coverage_calibrated", "coverage_acceptable"),
}


def _coerce(value: Any, annotation: Any, where: str) -> Any:
    """Convert a TOML value to the annotated type or raise ValueError naming `where`."""
    origin = get_origin(annotation)
    if origin is tuple:
        (element, _ellipsis) = get_args(annotation)
        if not isinstance(value, list):
            raise ValueError(f"{where}: expected a list, got {type(value).__name__}")
        return tuple(_coerce(v, element, where) for v in value)
    if annotation is bool:
        ok = isinstance(value, bool)
    elif annotation is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif annotation is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    elif annotation is str:
        ok = isinstance(value, str)
    elif annotation is Path:
        if isinstance(value, str):
            path = Path(value)
            return path if path.is_absolute() else PROJECT_ROOT / path
        ok = False
    else:  # pragma: no cover - only reachable by adding an unsupported annotation
        raise TypeError(f"{where}: unsupported annotation {annotation!r}")
    if not ok:
        raise ValueError(f"{where}: expected {getattr(annotation, '__name__', annotation)}, got {value!r}")
    return value


def _build_section(cls: type, data: Any, name: str) -> Any:
    if not isinstance(data, dict):
        raise ValueError(f"[{name}]: expected a table, got {type(data).__name__}")
    hints = get_type_hints(cls)
    fields = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"[{name}]: unknown key {unknown[0]!r}")
    missing = [f for f in fields if f not in data]
    if missing:
        raise ValueError(f"[{name}]: missing key {missing[0]!r}")
    values = {f: _coerce(data[f], hints[f], f"[{name}] {f}") for f in fields}
    for key in _PAIR_KEYS.get(name, ()):
        pair = values[key]
        if len(pair) != 2 or not pair[0] < pair[1]:
            raise ValueError(f"[{name}] {key}: expected an ordered (low, high) pair, got {list(pair)}")
    return cls(**values)


def _check(cfg: PipelineConfig) -> None:
    if cfg.source.mode not in ("http", "local"):
        raise ValueError(f"[source] mode: expected 'http' or 'local', got {cfg.source.mode!r}")
    if cfg.backtest.n_workers < 1:
        raise ValueError(f"[backtest] n_workers: expected a positive integer, got {cfg.backtest.n_workers}")


def _deep_merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Read a TOML file, following ``extends`` (relative to the file) and merging over its base."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"configuration file not found: {path}")
    resolved = path.resolve()
    if resolved in _seen:
        raise ValueError(f"configuration files extend each other in a loop at {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    if not isinstance(parent, str):
        raise ValueError(f"{path}: extends must be a path string")
    parent_path = Path(parent)
    if not parent_path.is_absolute():
        parent_path = path.parent / parent_path
    return _deep_merge(_read_toml(parent_path, (*_seen, resolved)), data)


def _workers_from_environment() -> int | None:
    raw = os.environ.get(ENV_N_WORKERS)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError(f"{ENV_N_WORKERS}: expected a positive integer, got {raw!r}")
    return value


def load_config(path: Path | None = None, overrides: Path | None = None) -> PipelineConfig:
    """Load the configuration.

    `path` is the main file; without it, ``$OILGAS_CONFIG`` and then ``config/pipeline.toml``.
    `overrides` is merged key by key over it. ``$OILGAS_N_WORKERS`` wins over both for
    ``backtest.n_workers``.
    """
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG
    data = _read_toml(Path(path))
    if overrides is not None:
        data = _deep_merge(data, _read_toml(Path(overrides)))
    workers = _workers_from_environment()
    if workers is not None:
        data = _deep_merge(data, {"backtest": {"n_workers": workers}})

    sections = [f.name for f in dataclasses.fields(PipelineConfig)]
    hints = get_type_hints(PipelineConfig)
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ValueError(f"unknown section [{unknown[0]}]")
    missing = [s for s in sections if s not in data]
    if missing:
        raise ValueError(f"missing section [{missing[0]}]")
    cfg = PipelineConfig(**{name: _build_section(hints[name], data[name], name) for name in sections})
    _check(cfg)
    return cfg
