"""Kommandoradsgränssnitt.

    python -m excel_merge.cli run     --spec config/relations.yaml [--build namn]
    python -m excel_merge.cli profile --spec config/relations.yaml
    python -m excel_merge.cli plan    --spec config/relations.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from excel_merge.config import ConfigError
from excel_merge.engine import BuildError, execute_build
from excel_merge.io import SourceReadError, read_sheet
from excel_merge.profile import discover_candidate_keys, format_comparison, suggest_spec_entry
from excel_merge.relations import RelationSpecError, build_plan, load_relation_spec


def _cmd_run(args: argparse.Namespace) -> int:
    spec = load_relation_spec(args.spec)
    build_names = [args.build] if args.build else [b.name for b in spec.builds]
    for name in build_names:
        result = execute_build(spec, name)
        for source, rows in result.row_counts.items():
            print(f"  läste {source}: {rows} rader")
        print(f"  [{name}] skrev {len(result.frame)} rader till {result.output_path}")
    return 0


def _cmd_profile(args: argparse.Namespace) -> int:
    """Visa underlag för hur källorna kan kopplas ihop."""
    config = load_relation_spec(args.spec)
    frames = {source.name: read_sheet(source, config.base_dir) for source in config.sources}

    print("Kolumnprofil per källa:")
    for name, frame in frames.items():
        print(f"  {name} ({len(frame)} rader)")
        for column in frame.columns:
            series = frame[column]
            nulls = int(series.isna().sum())
            distinct = int(series.dropna().nunique())
            print(f"    {column}: typ={series.dtype}, distinkta={distinct}, nollvärden={nulls}")

    entity_of = {source.name: source.entity for source in config.sources}
    names = list(frames)
    print("\nFöreslagna kopplingar (maskinellt underlag - bekräfta mot verksamheten):")
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            candidates = discover_candidate_keys(frames[left_name], frames[right_name])
            if not candidates:
                print(f"  {left_name} <-> {right_name}: inga uppenbara nycklar hittades")
                continue
            best = candidates[0]
            print(f"  {left_name} <-> {right_name}:")
            print(format_comparison(best))
            print("    utkast till spec-post:")
            # 'to' avser entiteten, inte källan - samma vokabulär som specen.
            print(suggest_spec_entry(best, entity_of.get(right_name, right_name)))
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    """Visa vilken körplan som härleds ur specen, utan att köra den."""
    spec = load_relation_spec(args.spec)
    for build in spec.builds:
        print(f"bygge '{build.name}' (bas: {build.base}):")
        for index, step in enumerate(build_plan(spec, build.name), start=1):
            print(
                f"  {index}. {step.source_name} -> entitet {step.entity} "
                f"(nyckel {step.key}, {step.cardinality}, orphans={step.orphans})"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Koppla ihop Excel-flikar till ett nytt ark.")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="kör flödet och skriv utdata")
    run_cmd.add_argument("--spec", required=True, type=Path, help="Sökväg till relationsspecen (YAML)")
    run_cmd.add_argument("--build", help="kör bara detta bygge (default: alla)")
    run_cmd.set_defaults(handler=_cmd_run)

    for name, handler, help_text in (
        ("profile", _cmd_profile, "profilera källorna och föreslå kopplingar"),
        ("plan", _cmd_plan, "visa härledd körplan"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--spec", required=True, type=Path, help="Sökväg till relationsspecen (YAML)")
        child.set_defaults(handler=handler)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, RelationSpecError, SourceReadError, BuildError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
