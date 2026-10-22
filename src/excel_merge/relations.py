"""Relationsmodell för godtyckligt antal källor.

När flödet växer från två flikar till många räcker inte en rak kedja av
sammanslagningar. Här beskrivs i stället *entiteter* och *relationer* mellan
dem, och en körplan härleds ur grafen.

Grundtanken: källor beskriver data, entiteter beskriver vad datan handlar om.
En källa tillhör en entitet och kan peka på andra entiteter via nycklar. Det gör
att tio källor kan kopplas ihop utan att någon skriver tio specialfall.

Besluten om *hur* något kopplas ihop (kardinalitet, vad som händer med
föräldralösa rader) ligger i specen, inte i koden. En agent kan därför föreslå
och ändra dem, medan testerna avgör om ändringen är rimlig.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}
ORPHAN_POLICIES = {"keep", "drop", "flag"}


class RelationSpecError(ValueError):
    """Relationsspecen är strukturellt felaktig eller motsägelsefull."""


@dataclass(frozen=True)
class Entity:
    name: str
    key: str
    description: str = ""


@dataclass(frozen=True)
class Relationship:
    to: str
    via: str
    cardinality: str = "many_to_one"
    orphans: str = "keep"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    path: Path
    sheet: str
    entity: str
    columns: dict[str, str]
    dtypes: dict[str, str] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)

    @property
    def required_input_columns(self) -> list[str]:
        """Originalkolumnerna som måste finnas i fliken."""
        return list(self.columns.keys())

    @property
    def output_columns(self) -> list[str]:
        return list(self.columns.values())


@dataclass(frozen=True)
class BuildSpec:
    name: str
    base: str
    include: list[str]
    output: Path
    sheet: str
    columns: list[str] | None = None


@dataclass(frozen=True)
class RelationSpec:
    entities: dict[str, Entity]
    sources: list[SourceSpec]
    builds: list[BuildSpec]
    version: int = 1
    base_dir: Path = Path(".")

    def entity_sources(self, entity: str) -> list[SourceSpec]:
        return [s for s in self.sources if s.entity == entity]


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise RelationSpecError(f"{ctx}: obligatoriskt fält '{key}' saknas")
    return mapping[key]


def _parse_relationship(raw: dict[str, Any], ctx: str) -> Relationship:
    cardinality = str(raw.get("cardinality", "many_to_one"))
    orphans = str(raw.get("orphans", "keep"))
    if cardinality not in CARDINALITIES:
        raise RelationSpecError(f"{ctx}.cardinality måste vara en av {sorted(CARDINALITIES)}, fick '{cardinality}'")
    if orphans not in ORPHAN_POLICIES:
        raise RelationSpecError(f"{ctx}.orphans måste vara en av {sorted(ORPHAN_POLICIES)}, fick '{orphans}'")
    return Relationship(
        to=str(_require(raw, "to", ctx)),
        via=str(_require(raw, "via", ctx)),
        cardinality=cardinality,
        orphans=orphans,
    )


def _parse_source(raw: dict[str, Any], index: int) -> SourceSpec:
    ctx = f"sources[{index}]"
    columns = _require(raw, "columns", ctx)
    if not isinstance(columns, dict) or not columns:
        raise RelationSpecError(f"{ctx}.columns måste vara en icke-tom mappning")
    return SourceSpec(
        name=str(_require(raw, "name", ctx)),
        path=Path(str(_require(raw, "path", ctx))),
        sheet=str(_require(raw, "sheet", ctx)),
        entity=str(_require(raw, "entity", ctx)),
        columns={str(k): str(v) for k, v in columns.items()},
        dtypes={str(k): str(v) for k, v in (raw.get("dtypes") or {}).items()},
        relationships=[_parse_relationship(r, f"{ctx}.relationships[{i}]")
                       for i, r in enumerate(raw.get("relationships") or [])],
    )


def _parse_build(raw: dict[str, Any], index: int) -> BuildSpec:
    ctx = f"builds[{index}]"
    include = raw.get("include") or []
    if not isinstance(include, list) or not include:
        raise RelationSpecError(f"{ctx}.include måste lista minst en entitet att berika basen med")
    return BuildSpec(
        name=str(_require(raw, "name", ctx)),
        base=str(_require(raw, "base", ctx)),
        include=[str(e) for e in include],
        output=Path(str(_require(raw, "output", ctx))),
        sheet=str(raw.get("sheet", "Sheet1")),
        columns=list(raw["columns"]) if raw.get("columns") else None,
    )


def load_relation_spec(path: str | Path) -> RelationSpec:
    path = Path(path)
    if not path.is_file():
        raise RelationSpecError(f"Relationsspecen hittades inte: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    entities_raw = _require(raw, "entities", "root")
    entities = {
        str(name): Entity(
            name=str(name),
            key=str(_require(body, "key", f"entities.{name}")),
            description=str(body.get("description", "")),
        )
        for name, body in entities_raw.items()
    }

    sources_raw = _require(raw, "sources", "root")
    sources = [_parse_source(s, i) for i, s in enumerate(sources_raw)]

    names = [s.name for s in sources]
    if len(set(names)) != len(names):
        raise RelationSpecError(f"källnamnen måste vara unika, fick: {names}")

    spec = RelationSpec(
        entities=entities,
        sources=sources,
        builds=[_parse_build(b, i) for i, b in enumerate(raw.get("builds") or [])],
        version=int(raw.get("version", 1)),
        base_dir=path.parent.resolve(),
    )
    _validate(spec)
    return spec


def _validate(spec: RelationSpec) -> None:
    for source in spec.sources:
        if source.entity not in spec.entities:
            raise RelationSpecError(
                f"källan '{source.name}' pekar på okänd entitet '{source.entity}'. "
                f"Definierade entiteter: {sorted(spec.entities)}"
            )
        entity_key = spec.entities[source.entity].key
        if entity_key not in source.output_columns:
            raise RelationSpecError(
                f"källan '{source.name}' saknar entitetens nyckelkolumn '{entity_key}' "
                f"(entitet '{source.entity}') bland kolumnerna {source.output_columns}"
            )
        for rel in source.relationships:
            if rel.to not in spec.entities:
                raise RelationSpecError(
                    f"källan '{source.name}' har en relation till okänd entitet '{rel.to}'"
                )
            if rel.via not in source.output_columns:
                raise RelationSpecError(
                    f"källan '{source.name}' har en relation via kolumnen '{rel.via}' som inte finns "
                    f"bland kolumnerna {source.output_columns}"
                )

    for build in spec.builds:
        if build.base not in spec.entities:
            raise RelationSpecError(f"bygget '{build.name}' har okänd bas-entitet '{build.base}'")
        if not spec.entity_sources(build.base):
            raise RelationSpecError(f"bygget '{build.name}': ingen källa tillhandahåller bas-entiteten '{build.base}'")
        for entity in build.include:
            if entity not in spec.entities:
                raise RelationSpecError(f"bygget '{build.name}' inkluderar okänd entitet '{entity}'")
            if not spec.entity_sources(entity):
                raise RelationSpecError(
                    f"bygget '{build.name}': ingen källa tillhandahåller entiteten '{entity}'"
                )
        reachable = _reachable_entities(spec, build.base)
        for entity in build.include:
            if entity not in reachable:
                raise RelationSpecError(
                    f"bygget '{build.name}': entiteten '{entity}' går inte att nå från basen "
                    f"'{build.base}' via de relationer som är definierade"
                )


def _adjacency(spec: RelationSpec) -> dict[str, set[str]]:
    """Riktningslös angränsning mellan entiteter, härledd ur källornas relationer."""
    graph: dict[str, set[str]] = {name: set() for name in spec.entities}
    for source in spec.sources:
        for rel in source.relationships:
            graph[source.entity].add(rel.to)
            graph[rel.to].add(source.entity)
    return graph


def _reachable_entities(spec: RelationSpec, start: str) -> set[str]:
    graph = _adjacency(spec)
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop()
        for neighbour in graph[current]:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


@dataclass(frozen=True)
class PlanStep:
    source_name: str
    entity: str
    key: str
    cardinality: str
    orphans: str


def build_plan(spec: RelationSpec, build_name: str) -> list[PlanStep]:
    """Härled en ordnad körplan för ett bygge.

    Bas-entitetens källa kommer först. Därefter läggs entiteter i bredd-först-
    ordning utifrån hur de hänger ihop med basen, så att varje steg kan kopplas
    mot något som redan finns i resultatet.
    """
    build = next((b for b in spec.builds if b.name == build_name), None)
    if build is None:
        raise RelationSpecError(f"okänt bygge '{build_name}'. Definierade: {[b.name for b in spec.builds]}")

    wanted = [build.base, *build.include]
    graph = _adjacency(spec)

    order: list[str] = [build.base]
    frontier = [build.base]
    while frontier:
        next_frontier: list[str] = []
        for current in frontier:
            for neighbour in sorted(graph[current]):
                if neighbour in wanted and neighbour not in order:
                    order.append(neighbour)
                    next_frontier.append(neighbour)
        frontier = next_frontier

    steps: list[PlanStep] = []
    for entity in order:
        candidates = spec.entity_sources(entity)
        if not candidates:
            raise RelationSpecError(f"ingen källa tillhandahåller entiteten '{entity}'")
        # Vid flera källor per entitet väljs den första; en framtida regel kan
        # välja baserat på kolumntäckning eller prioritet i specen.
        chosen = candidates[0]
        step = _step_for(spec, chosen, entity, order)
        steps.append(step)
    return steps


def _step_for(spec: RelationSpec, source: SourceSpec, entity: str, order: list[str]) -> PlanStep:
    """Bestäm hur källan ska kopplas in i resultatet."""
    if entity == order[0]:
        return PlanStep(source.name, entity, spec.entities[entity].key, "one_to_one", "keep")

    for rel in source.relationships:
        if rel.to in order:
            return PlanStep(source.name, entity, rel.via, rel.cardinality, rel.orphans)
    return PlanStep(source.name, entity, spec.entities[entity].key, "many_to_one", "keep")
