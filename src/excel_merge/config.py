"""Inläsning och validering av pipeline-konfigurationen."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ALLOWED_JOIN_HOW = {"left", "right", "inner", "outer"}
_ALLOWED_VALIDATE = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}


class ConfigError(ValueError):
    """Konfigurationen är strukturellt felaktig eller inkonsekvent."""


@dataclass(frozen=True)
class SourceConfig:
    name: str
    path: Path
    sheet: str
    columns: dict[str, str]
    dtypes: dict[str, str] = field(default_factory=dict)

    @property
    def required_input_columns(self) -> list[str]:
        return list(self.columns.keys())

    @property
    def output_columns(self) -> list[str]:
        return list(self.columns.values())


@dataclass(frozen=True)
class JoinConfig:
    on: list[str]
    how: str = "left"
    validate: str | None = None


@dataclass(frozen=True)
class OutputConfig:
    path: Path
    sheet: str
    columns: list[str] | None = None


@dataclass(frozen=True)
class PipelineConfig:
    sources: list[SourceConfig]
    join: JoinConfig
    output: OutputConfig
    version: int = 1
    base_dir: Path = Path(".")

    def resolve(self, path: Path) -> Path:
        """Tolka sökvägar relativt konfigurationsfilens katalog."""
        return path if path.is_absolute() else (self.base_dir / path).resolve()


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"{ctx}: obligatoriskt fält '{key}' saknas")
    return mapping[key]


def _join_keys(join_raw: dict[str, Any]) -> list[Any]:
    """Hämta join-nycklarna.

    YAML 1.1 (PyYAML) tolkar den obestämda nyckeln ``on:`` som boolean True,
    så vi accepterar både ``on`` och det parsade värdet True.
    """
    for candidate in ("on", True):
        if candidate in join_raw:
            return join_raw[candidate]
    raise ConfigError("join: obligatoriskt fält 'on' saknas")


def _parse_source(raw: dict[str, Any], index: int) -> SourceConfig:
    ctx = f"sources[{index}]"
    columns = _require(raw, "columns", ctx)
    if not isinstance(columns, dict) or not columns:
        raise ConfigError(f"{ctx}.columns måste vara en icke-tom mappning original->nytt namn")
    dtypes = raw.get("dtypes", {}) or {}
    unknown = set(dtypes) - set(columns)
    if unknown:
        raise ConfigError(f"{ctx}.dtypes refererar till okända kolumner: {sorted(unknown)}")
    return SourceConfig(
        name=str(_require(raw, "name", ctx)),
        path=Path(str(_require(raw, "path", ctx))),
        sheet=str(_require(raw, "sheet", ctx)),
        columns={str(k): str(v) for k, v in columns.items()},
        dtypes={str(k): str(v) for k, v in dtypes.items()},
    )


def load_config(path: str | Path) -> PipelineConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Konfigurationsfilen hittades inte: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    sources_raw = _require(raw, "sources", "root")
    if not isinstance(sources_raw, list) or len(sources_raw) < 2:
        raise ConfigError("root.sources måste vara en lista med minst två källor att koppla ihop")

    sources = [_parse_source(s, i) for i, s in enumerate(sources_raw)]
    names = [s.name for s in sources]
    if len(set(names)) != len(names):
        raise ConfigError(f"källnamnen måste vara unika, fick: {names}")

    join_raw = _require(raw, "join", "root")
    join = JoinConfig(
        on=[str(c) for c in _join_keys(join_raw)],
        how=str(join_raw.get("how", "left")),
        validate=(None if join_raw.get("validate") in (None, "", "none") else str(join_raw["validate"])),
    )
    if join.how not in _ALLOWED_JOIN_HOW:
        raise ConfigError(f"join.how måste vara en av {sorted(_ALLOWED_JOIN_HOW)}, fick '{join.how}'")
    if join.validate is not None and join.validate not in _ALLOWED_VALIDATE:
        raise ConfigError(f"join.validate måste vara en av {sorted(_ALLOWED_VALIDATE)}, fick '{join.validate}'")

    # Nyckelkolumnerna måste finnas i varje källa, annars är flödet ogenomförbart.
    for source in sources:
        missing = [c for c in join.on if c not in source.output_columns]
        if missing:
            raise ConfigError(f"källan '{source.name}' saknar nyckelkolumn(er) {missing} som krävs av join.on")

    output_raw = _require(raw, "output", "root")
    output = OutputConfig(
        path=Path(str(_require(output_raw, "path", "output"))),
        sheet=str(output_raw.get("sheet", "Sheet1")),
        columns=list(output_raw["columns"]) if output_raw.get("columns") else None,
    )
    if output.columns:
        available = {c for s in sources for c in s.output_columns}
        missing = [c for c in output.columns if c not in available]
        if missing:
            raise ConfigError(f"output.columns refererar till kolumner som inte produceras: {missing}")

    return PipelineConfig(
        sources=sources,
        join=join,
        output=output,
        version=int(raw.get("version", 1)),
        base_dir=path.parent.resolve(),
    )
