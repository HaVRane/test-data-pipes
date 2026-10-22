"""Körmotor som verkställer en körplan ur relationsspecen.

Motorn är generisk: den vet ingenting om kunder eller ordrar, bara om
entiteter, nycklar och policies. Att lägga till en källa handlar därför om att
lägga till en post i specen, inte om att skriva ny kod här.

Policyn ``orphans`` styr kopplingen:
  keep -> vänsterkoppling, alla basrader behålls
  drop -> innerkoppling, basrader utan match tas bort
  flag -> vänsterkoppling plus en kolumn som markerar om matchningen lyckades
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from excel_merge.io import read_sheet, write_sheet
from excel_merge.relations import RelationSpec, build_plan

_ORPHAN_TO_HOW = {"keep": "left", "drop": "inner", "flag": "left"}


class BuildError(RuntimeError):
    """Bygget kunde inte genomföras som specen föreskriver."""


@dataclass
class BuildResult:
    frame: pd.DataFrame
    output_path: Path
    row_counts: dict[str, int]


def _merge_once(
    accumulated: pd.DataFrame,
    incoming: pd.DataFrame,
    key: str,
    cardinality: str,
    orphans: str,
    label: str,
) -> pd.DataFrame:
    if key not in accumulated.columns or key not in incoming.columns:
        raise BuildError(
            f"nyckelkolumnen '{key}' saknas vid koppling av '{label}': "
            f"ackumulerat {list(accumulated.columns)}, inkommande {list(incoming.columns)}"
        )

    how = _ORPHAN_TO_HOW[orphans]
    indicator = f"matched_{label}" if orphans == "flag" else False

    try:
        merged = accumulated.merge(
            incoming,
            on=key,
            how=how,
            validate=cardinality if cardinality != "many_to_many" else None,
            suffixes=("", f"_{label}"),
            indicator=indicator,
        )
    except pd.errors.MergeError as exc:
        raise BuildError(
            f"kopplingen av '{label}' bröt mot kardinaliteten '{cardinality}': {exc}"
        ) from exc

    if orphans == "flag":
        merged[f"matched_{label}"] = merged[f"matched_{label}"].eq("both")
    return merged


def execute_build(spec: RelationSpec, build_name: str) -> BuildResult:
    build = next((b for b in spec.builds if b.name == build_name), None)
    if build is None:
        raise BuildError(f"okänt bygge '{build_name}'")

    plan = build_plan(spec, build_name)
    by_name = {s.name: s for s in spec.sources}

    accumulated: pd.DataFrame | None = None
    row_counts: dict[str, int] = {}

    for step in plan:
        source = by_name[step.source_name]
        incoming = read_sheet(source, spec.base_dir)
        row_counts[source.name] = len(incoming)

        if accumulated is None:
            accumulated = incoming
            continue

        accumulated = _merge_once(
            accumulated,
            incoming,
            key=step.key,
            cardinality=step.cardinality,
            orphans=step.orphans,
            label=step.source_name,
        )

    assert accumulated is not None
    if build.columns:
        missing = [c for c in build.columns if c not in accumulated.columns]
        if missing:
            raise BuildError(f"build.columns saknas efter koppling: {missing}")
        # Diagnostikkolumner från orphans=flag behålls även om de inte listas,
        # annars försvinner själva poängen med att flagga.
        markers = [c for c in accumulated.columns if c.startswith("matched_")]
        accumulated = accumulated[[*build.columns, *[m for m in markers if m not in build.columns]]]

    output_path = write_sheet(accumulated, _as_output(build), spec.base_dir)
    return BuildResult(frame=accumulated, output_path=output_path, row_counts=row_counts)


def _as_output(build):
    from excel_merge.config import OutputConfig

    return OutputConfig(path=build.output, sheet=build.sheet)
