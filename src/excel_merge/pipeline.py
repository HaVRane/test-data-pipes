"""Själva dataflödet: läs källor -> koppla ihop -> skriv ut."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from excel_merge.config import PipelineConfig
from excel_merge.io import read_sheet, write_sheet


class PipelineError(RuntimeError):
    """Dataflödet kunde inte genomföras som konfigurerat."""


@dataclass
class PipelineResult:
    frame: pd.DataFrame
    output_path: Path
    row_counts: dict[str, int]


def merge_sources(config: PipelineConfig) -> pd.DataFrame:
    """Läs alla källor och koppla ihop dem på join-nyckeln."""
    frames = {source.name: read_sheet(source, config.base_dir) for source in config.sources}

    joined: pd.DataFrame | None = None
    for name, frame in frames.items():
        if joined is None:
            joined = frame
            continue
        missing_keys = [k for k in config.join.on if k not in frame.columns]
        if missing_keys:
            raise PipelineError(f"källan '{name}' saknar nyckelkolumn(er) {missing_keys} vid sammanslagning")
        try:
            joined = joined.merge(
                frame,
                on=config.join.on,
                how=config.join.how,
                validate=config.join.validate,
                suffixes=("", f"_{name}"),
            )
        except pd.errors.MergeError as exc:
            raise PipelineError(f"sammanslagningen misslyckades (validate={config.join.validate}): {exc}") from exc

    assert joined is not None  # load_config garanterar minst två källor
    return joined


def run_pipeline(config: PipelineConfig) -> PipelineResult:
    joined = merge_sources(config)

    if config.output.columns:
        missing = [c for c in config.output.columns if c not in joined.columns]
        if missing:
            raise PipelineError(f"output.columns saknas efter sammanslagning: {missing}")
        joined = joined[config.output.columns]

    output_path = write_sheet(joined, config.output, config.base_dir)
    row_counts = {s.name: len(read_sheet(s, config.base_dir)) for s in config.sources}
    return PipelineResult(frame=joined, output_path=output_path, row_counts=row_counts)
