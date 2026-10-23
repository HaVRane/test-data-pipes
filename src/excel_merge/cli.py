"""Kommandoradsgränssnitt.

    python -m excel_merge.cli run      --spec config/relations.yaml [--build namn]
    python -m excel_merge.cli profile  --spec config/relations.yaml
    python -m excel_merge.cli plan     --spec config/relations.yaml
    python -m excel_merge.cli subjects --spec config/relations.yaml
    python -m excel_merge.cli watch    --spec config/relations.yaml
    python -m excel_merge.cli log      --spec config/relations.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from excel_merge.changelog import ChangeLog
from excel_merge.config import ConfigError
from excel_merge.engine import BuildError, execute_build
from excel_merge.io import SourceReadError, read_sheet
from excel_merge.profile import discover_candidate_keys, format_comparison, suggest_spec_entry
from excel_merge.relations import RelationSpecError, build_plan, load_relation_spec, resolve_present_spec
from excel_merge.subjects import derive_subjects, load_frames
from excel_merge.watch import run_watch

DEFAULT_LOG = "state/changelog.ndjson"
DEFAULT_STATE = "state/sources.json"


def _cmd_watch(args: argparse.Namespace) -> int:
    """Upptäck ändringar i datat och skriv dem till loggen."""
    spec = load_relation_spec(args.spec)
    events = run_watch(
        spec,
        args.log,
        args.state,
        timestamp=args.timestamp,
        verbose=args.verbose,
    )

    if not events:
        print("Inga ändringar sedan förra körningen.")
        return 0

    for event in events:
        if event.event == "source_unchanged" and not args.verbose:
            continue
        print(event.describe())
    print(f"\n{len(events)} händelse(r) skrivna till {args.log}")
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    """Visa ändringsloggen, nyast först."""
    log = ChangeLog(args.log, args.state)
    events = log.read_events()
    if not events:
        print(f"Ingen logg ännu ({log.log_path}). Kör 'watch' först.")
        return 0

    selected = events
    if args.event:
        selected = [e for e in selected if e.get("event") == args.event]
    if args.source:
        selected = [e for e in selected if e.get("source") == args.source]

    for event in reversed(selected[-args.limit :] if args.limit else selected):
        stamp = event.get("timestamp", "")
        kind = event.get("event", "")
        source = event.get("source", "")
        if kind == "source_added":
            detail = f"{event.get('rows', '?')} rader"
        elif kind == "source_removed":
            detail = f"senast {event.get('last_seen', '?')}"
            if event.get("reason"):
                detail += f", {event['reason']}"
        elif kind == "source_changed":
            if event.get("rows_before") is None:
                detail = f"läsbar igen, {event.get('rows', '?')} rader"
            else:
                detail = (
                    f"{event.get('rows_before')} -> {event.get('rows')} rader"
                    f", {event.get('fingerprint_before')} -> {event.get('fingerprint_after')}"
                )
        elif kind == "source_unreadable":
            detail = event.get("error", "okänt fel")
        elif kind == "source_recovered":
            detail = f"läsbar igen, {event.get('rows', '?')} rader"
        else:
            detail = f"{event.get('rows', '?')} rader"
        print(f"{stamp}  {kind:<18} {source:<24} {detail}")
    return 0


def _drop_missing_sources(spec):
    """Ta bort källor vars fil eller flik saknas, och säg till om det.

    En saknad källa finns inte längre. Den ska därför behandlas precis som om
    posten struktis ur specen. Att säga till högt är viktigt: annars kan en
    felstavad sökväg försvinna tyst och bygget se ut att lyckas.
    """
    missing = spec.missing_source_names()
    for name in missing:
        print(
            f"! {name}: filen eller fliken saknas - källan tas bort ur modellen",
            file=sys.stderr,
        )
    return resolve_present_spec(spec) if missing else spec


def _cmd_run(args: argparse.Namespace) -> int:
    spec = _drop_missing_sources(load_relation_spec(args.spec))
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
    config = _drop_missing_sources(config)
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
    spec = _drop_missing_sources(load_relation_spec(args.spec))
    for build in spec.builds:
        print(f"bygge '{build.name}' (bas: {build.base}):")
        for index, step in enumerate(build_plan(spec, build.name), start=1):
            print(
                f"  {index}. {step.source_name} -> entitet {step.entity} "
                f"(nyckel {step.key}, {step.cardinality}, orphans={step.orphans})"
            )
    return 0


def _cmd_subjects(args: argparse.Namespace) -> int:
    """Visa härledda ämnesområden: fakta, dimensioner och mått.

    Detta är en vy över specen, inte en ändring av den. Ingenting skrivs
    tillbaka, och klassningen är regelbaserad - därför kan den köras utan att
    någon granskar den först.
    """
    spec = _drop_missing_sources(load_relation_spec(args.spec))
    model = derive_subjects(spec, frames=load_frames(spec))

    if not model.subjects:
        print("Inga ämnesområden kunde härledas - specen saknar källor.")
        return 0

    for subject in model.subjects:
        print(f"ämnesområde: {subject.name}")
        print(f"  {subject.reason}")
        for fact in subject.facts:
            print(f"  fakta: {fact.entity} (nyckel {fact.key}, källor: {', '.join(fact.sources)})")
            print(f"    radnivå: {fact.grain}")
            for measure in fact.measures:
                print(f"    mått: {measure.column} [{measure.kind}]")
            for key in fact.foreign_keys:
                print(f"    främmande nyckel: {key.column} -> {key.to_entity} ({key.cardinality})")
        for dimension in subject.dimensions:
            attributes = ", ".join(dimension.attributes) or "inga"
            print(f"  dimension: {dimension.entity} (nyckel {dimension.key})")
            print(f"    attribut: {attributes}")
        print()

    if model.conformed:
        print("konforma dimensioner (delas av flera ämnesområden):")
        for conformed in model.conformed:
            print(f"  {conformed.entity}: {', '.join(conformed.subjects)}")
        print()

    if model.unassigned:
        print("entiteter utanför varje ämnesområde:")
        for unassigned in model.unassigned:
            print(f"  {unassigned.entity}: {unassigned.reason}")
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
        ("subjects", _cmd_subjects, "visa härledda ämnesområden, fakta och mått"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--spec", required=True, type=Path, help="Sökväg till relationsspecen (YAML)")
        child.set_defaults(handler=handler)

    watch = sub.add_parser("watch", help="upptäck ändringar i källorna och logga dem")
    watch.add_argument("--spec", required=True, type=Path, help="Sökväg till relationsspecen (YAML)")
    watch.add_argument("--log", type=Path, default=Path(DEFAULT_LOG), help=f"loggfil (default: {DEFAULT_LOG})")
    watch.add_argument("--state", type=Path, default=Path(DEFAULT_STATE), help=f"tillståndsfil (default: {DEFAULT_STATE})")
    watch.add_argument("--verbose", action="store_true", help="logga även oförändrade källor")
    watch.add_argument("--timestamp", default=None, help="tidpunkt att stämpla (ISO 8601), för tester")
    watch.set_defaults(handler=_cmd_watch)

    log_cmd = sub.add_parser("log", help="visa ändringsloggen")
    log_cmd.add_argument("--log", type=Path, default=Path(DEFAULT_LOG), help=f"loggfil (default: {DEFAULT_LOG})")
    log_cmd.add_argument("--state", type=Path, default=Path(DEFAULT_STATE))
    log_cmd.add_argument(
        "--event",
        choices=[
            "source_added", "source_removed", "source_changed",
            "source_unchanged", "source_unreadable", "source_recovered",
        ],
        help="visa bara denna händelsetyp",
    )
    log_cmd.add_argument("--source", help="visa bara denna källa")
    log_cmd.add_argument("--limit", type=int, default=0, help="visa bara de N senaste")
    log_cmd.set_defaults(handler=_cmd_log)

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
