"""Härledda ämnesområden: fakta, dimensioner och mått ur relationsspecen.

Relationsspecen beskriver *vad* datan handlar om - entiteter, nycklar och hur de
hänger ihop. Den beskriver inte *hur datan ska läsas*: vilka tabeller som är
fakta, vilka som är dimensioner och vilka kolumner som är mått. Det är härlett,
och den här modulen gör det.

Härledningen är avsiktligt regelbaserad och deterministisk, utan språkmodell.
Skälet är att en klassning ska kunna förklaras och testas. Varje roll bär sitt
skäl, och en entitet som inte går att placera får förbli oklassad i stället för
att tvingas in i en roll.

Gränsen mot kardinalitet och orphaning-policy är viktig. De är affärsbeslut som
en människa måste bekräfta, eftersom de styr vad som skrivs ut. Ämnesområdena är
en *vy* över specen: de skriver ingenting tillbaka, och en felaktig klassning
förstör ingen data. Därför kan de härledas helt automatiskt. Gränsen går vid
skrivning, inte vid läsning.

Klassningen följer dimensionell modellering:

  - En **fakta** är en entitet som går att mäta på: den har mått (tal eller
    tidpunkter) utöver sin nyckel och sina främmande nycklar.
  - En **dimension** är en entitet som beskriver något. Dess kolumner är
    attribut, och den pekas på av fakta.
  - Ett **mått** är en kolumn som går att summera eller jämföra över tid.
  - En **konform dimension** används av mer än ett ämnesområde. Det är samma
    begrepp på flera ställen, och därför värt att se separat.

Ett ämnesområde motsvarar ett bygge, eftersom bygget redan definierar en
sammanhängande grupp. Saknas byggen härleds ett ämnesområde per sammanhängande
del av entitetsgrafen, så att vyn fungerar även innan något bygge skrivits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from excel_merge.profile import column_kind
from excel_merge.relations import RelationSpec, SourceSpec

# Mått är tal eller tidpunkter. Text går inte att summera och är därför attribut.
_MEASURE_KINDS = {"numeric", "datetime"}


@dataclass(frozen=True)
class Measure:
    """En kolumn som går att mäta på."""

    column: str
    source_column: str
    source: str
    kind: str
    reason: str


@dataclass(frozen=True)
class ForeignKey:
    """En kolumn som pekar på en annan entitet."""

    column: str
    to_entity: str
    cardinality: str
    orphans: str


@dataclass(frozen=True)
class Dimension:
    """En entitet som beskriver något, med sina attribut."""

    entity: str
    key: str
    sources: list[str]
    attributes: list[str]
    reason: str


@dataclass(frozen=True)
class Fact:
    """En entitet som går att mäta på."""

    entity: str
    key: str
    sources: list[str]
    grain: str
    measures: list[Measure]
    foreign_keys: list[ForeignKey]
    reason: str


@dataclass(frozen=True)
class SubjectArea:
    """Ett sammanhängande ämnesområde: en fakta med sina dimensioner."""

    name: str
    facts: list[Fact]
    dimensions: list[Dimension]
    reason: str

    @property
    def measures(self) -> list[Measure]:
        return [m for fact in self.facts for m in fact.measures]


@dataclass(frozen=True)
class ConformedDimension:
    """En dimension som används av fler än ett ämnesområde."""

    entity: str
    key: str
    subjects: list[str]
    reason: str


@dataclass(frozen=True)
class UnassignedEntity:
    """En entitet som inte hamnat i något ämnesområde."""

    entity: str
    sources: list[str]
    reason: str


@dataclass(frozen=True)
class SubjectModel:
    subjects: list[SubjectArea]
    conformed: list[ConformedDimension]
    unassigned: list[UnassignedEntity] = field(default_factory=list)


def load_frames(spec: RelationSpec, base_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    """Läs varje närvarande källa. Oläsbara källor hoppas över.

    En trasig fil ska inte krascha vyn. Den rapporteras redan av ``watch``, och
    här bidrar den bara med ingenting.
    """
    from excel_merge.io import SourceReadError, read_sheet

    root = base_dir or spec.base_dir
    frames: dict[str, pd.DataFrame] = {}
    for source in spec.present_sources():
        try:
            frames[source.name] = read_sheet(source, root)
        except SourceReadError:
            continue
    return frames


def _sources_of(spec: RelationSpec, entity: str) -> list[SourceSpec]:
    return spec.entity_sources(entity)


def _column_kinds(
    frames: dict[str, pd.DataFrame],
    source: SourceSpec,
) -> dict[str, str]:
    """Kolumnernas slag, per utdatakolumnnamn.

    Föredrar att läsa filen, eftersom verkliga värden är säkrare än deklarerade
    typer. Saknas filen används ``dtypes`` ur specen, så att klassningen blir
    användbar även innan datat finns - en kolumn som specen säger är ``float``
    är ett mått oavsett om filen går att öppna.
    """
    frame = frames.get(source.name)
    if frame is not None:
        return {str(column): column_kind(frame[column]) for column in frame.columns}

    declared: dict[str, str] = {}
    for original, dtype in source.dtypes.items():
        output = source.columns.get(original, original)
        declared[output] = _dtype_kind(dtype)
    return declared


def _dtype_kind(dtype: str) -> str:
    """Översätt en deklarerad dtype i specen till ett kolumnslag."""
    lowered = str(dtype).lower()
    if any(token in lowered for token in ("int", "float", "decimal", "number")):
        return "numeric"
    if any(token in lowered for token in ("datetime", "date", "time")):
        return "datetime"
    return "text"


def _reserved_columns(spec: RelationSpec, source: SourceSpec) -> set[str]:
    """Kolumner som inte kan vara mått: nycklar och främmande nycklar.

    En nyckel identifierar en rad, och en främmande nyckel är en referens. Att
    summera någon av dem vore meningslöst, även när de råkar vara tal.
    """
    reserved = {spec.entities[source.entity].key}
    for rel in source.relationships:
        reserved.add(rel.via)
    if source.row_key:
        reserved.add(source.row_key)
    return reserved


def _measures_for(
    spec: RelationSpec,
    entity: str,
    sources: list[SourceSpec],
    frames: dict[str, pd.DataFrame],
) -> list[Measure]:
    """Mått för en entitet, samlade över alla dess källor."""
    measures: list[Measure] = []
    for source in sources:
        kinds = _column_kinds(frames, source)
        reserved = _reserved_columns(spec, source)
        for original, output in source.columns.items():
            if output in reserved:
                continue
            kind = kinds.get(output)
            if kind not in _MEASURE_KINDS:
                continue
            measures.append(
                Measure(
                    column=output,
                    source_column=original,
                    source=source.name,
                    kind=kind,
                    reason=(
                        f"kolumnen '{original}' är {_kind_word(kind)} och är varken "
                        f"nyckel eller främmande nyckel"
                    ),
                )
            )
    return sorted(measures, key=lambda m: (m.source, m.column))


def _kind_word(kind: str) -> str:
    return {"numeric": "ett tal", "datetime": "en tidpunkt"}.get(kind, "en textkolumn")


def _attributes_for(
    spec: RelationSpec,
    entity: str,
    sources: list[SourceSpec],
    frames: dict[str, pd.DataFrame],
) -> list[str]:
    """Attribut: kolumnerna som varken är nyckel, främmande nyckel eller mått."""
    attributes: list[str] = []
    for source in sources:
        kinds = _column_kinds(frames, source)
        reserved = _reserved_columns(spec, source)
        for output in source.columns.values():
            if output in reserved or output in attributes:
                continue
            if kinds.get(output) in _MEASURE_KINDS:
                continue
            attributes.append(output)
    return sorted(attributes)


def _foreign_keys_for(sources: list[SourceSpec]) -> list[ForeignKey]:
    keys: list[ForeignKey] = []
    for source in sources:
        for rel in source.relationships:
            keys.append(
                ForeignKey(
                    column=rel.via,
                    to_entity=rel.to,
                    cardinality=rel.cardinality,
                    orphans=rel.orphans,
                )
            )
    return sorted(keys, key=lambda k: (k.to_entity, k.column))


def _grain(entity: str, key: str, sources: list[SourceSpec], measures: list[Measure]) -> str:
    """Beskriv radnivån i en mening."""
    if not measures:
        return f"en rad per {key}"
    unique_sides = {
        rel.cardinality
        for source in sources
        for rel in source.relationships
    }
    if "many_to_one" in unique_sides or "one_to_one" in unique_sides:
        return f"en rad per {key} och de nycklar den pekar på"
    return f"en rad per {key}"


def _component_subjects(spec: RelationSpec) -> list[list[str]]:
    """Sammanhängande delar av entitetsgrafen, för fallet utan byggen."""
    graph: dict[str, set[str]] = {name: set() for name in spec.entities}
    for source in spec.sources:
        for rel in source.relationships:
            graph[source.entity].add(rel.to)
            graph[rel.to].add(source.entity)

    seen: set[str] = set()
    components: list[list[str]] = []
    for name in sorted(spec.entities):
        if name in seen:
            continue
        component = {name}
        queue = [name]
        while queue:
            current = queue.pop()
            for neighbour in graph[current]:
                if neighbour not in component:
                    component.add(neighbour)
                    queue.append(neighbour)
        seen |= component
        components.append(sorted(component))
    return components


def _classify(
    spec: RelationSpec,
    entities: list[str],
    frames: dict[str, pd.DataFrame],
) -> tuple[list[Fact], list[Dimension]]:
    """Dela upp en grupp entiteter i fakta och dimensioner."""
    facts: list[Fact] = []
    dimensions: list[Dimension] = []

    for entity in entities:
        sources = _sources_of(spec, entity)
        if not sources:
            continue
        key = spec.entities[entity].key
        measures = _measures_for(spec, entity, sources, frames)
        names = [s.name for s in sources]

        if measures:
            facts.append(
                Fact(
                    entity=entity,
                    key=key,
                    sources=names,
                    grain=_grain(entity, key, sources, measures),
                    measures=measures,
                    foreign_keys=_foreign_keys_for(sources),
                    reason=(
                        f"entiteten '{entity}' har {len(measures)} mått "
                        f"({', '.join(m.column for m in measures)}) och går därför att mäta på"
                    ),
                )
            )
        else:
            attributes = _attributes_for(spec, entity, sources, frames)
            dimensions.append(
                Dimension(
                    entity=entity,
                    key=key,
                    sources=names,
                    attributes=attributes,
                    reason=(
                        f"entiteten '{entity}' har inga mått, bara beskrivande kolumner "
                        f"({', '.join(attributes) if attributes else 'inga'})"
                    ),
                )
            )
    return facts, dimensions


def derive_subjects(
    spec: RelationSpec,
    frames: dict[str, pd.DataFrame] | None = None,
) -> SubjectModel:
    """Härled ämnesområden, fakta, dimensioner och mått ur specen.

    Ett ämnesområde per bygge. Saknas byggen härleds ett per sammanhängande del
    av entitetsgrafen, så att vyn är användbar även innan något bygge skrivits.
    """
    frames = frames if frames is not None else load_frames(spec)
    subjects: list[SubjectArea] = []
    covered: set[str] = set()

    for build in spec.builds:
        entities = [build.base, *build.include]
        entities = [e for e in entities if spec.entity_sources(e)]
        covered |= set(entities)
        facts, dimensions = _classify(spec, entities, frames)
        subjects.append(
            SubjectArea(
                name=build.name,
                facts=facts,
                dimensions=dimensions,
                reason=(
                    f"härlett ur bygget '{build.name}' (bas: {build.base}, "
                    f"inkluderar: {', '.join(build.include)})"
                ),
            )
        )

    if not spec.builds:
        for component in _component_subjects(spec):
            present = [e for e in component if spec.entity_sources(e)]
            if not present:
                continue
            covered |= set(present)
            facts, dimensions = _classify(spec, present, frames)
            subjects.append(
                SubjectArea(
                    name="+".join(present),
                    facts=facts,
                    dimensions=dimensions,
                    reason=(
                        "inget bygge finns, så området härleddes ur en sammanhängande "
                        f"del av entitetsgrafen: {', '.join(present)}"
                    ),
                )
            )

    # Entiteter som har källor men inte nämns i något bygge. De får inte
    # försvinna tyst - samma princip som att ingen uppladdad fil får ignoreras.
    unassigned = [
        UnassignedEntity(
            entity=name,
            sources=[s.name for s in spec.entity_sources(name)],
            reason=(
                f"entiteten '{name}' har {len(spec.entity_sources(name))} källa(or) "
                "men ingår inte i något bygge och nämns därför inte i något ämnesområde"
            ),
        )
        for name in sorted(spec.entities)
        if name not in covered and spec.entity_sources(name)
    ]

    return SubjectModel(
        subjects=subjects,
        conformed=_conformed(subjects),
        unassigned=unassigned,
    )


def _conformed(subjects: list[SubjectArea]) -> list[ConformedDimension]:
    """Dimensioner som används av fler än ett ämnesområde."""
    usage: dict[str, list[str]] = {}
    keys: dict[str, str] = {}
    for subject in subjects:
        for dimension in subject.dimensions:
            usage.setdefault(dimension.entity, []).append(subject.name)
            keys.setdefault(dimension.entity, dimension.key)

    conformed = [
        ConformedDimension(
            entity=entity,
            key=keys[entity],
            subjects=sorted(names),
            reason=(
                f"dimensionen '{entity}' används av {len(names)} ämnesområden "
                f"({', '.join(sorted(names))}) och betyder därför samma sak i alla"
            ),
        )
        for entity, names in usage.items()
        if len(names) > 1
    ]
    return sorted(conformed, key=lambda c: c.entity)


def subject_model_to_dict(model: SubjectModel) -> dict:
    """JSON-vänlig form, för webbappens endpoint och för tester."""
    return {
        "subjects": [
            {
                "name": s.name,
                "reason": s.reason,
                "facts": [
                    {
                        "entity": f.entity,
                        "key": f.key,
                        "sources": f.sources,
                        "grain": f.grain,
                        "reason": f.reason,
                        "measures": [
                            {
                                "column": m.column,
                                "source_column": m.source_column,
                                "source": m.source,
                                "kind": m.kind,
                                "reason": m.reason,
                            }
                            for m in f.measures
                        ],
                        "foreign_keys": [
                            {
                                "column": k.column,
                                "to_entity": k.to_entity,
                                "cardinality": k.cardinality,
                                "orphans": k.orphans,
                            }
                            for k in f.foreign_keys
                        ],
                    }
                    for f in s.facts
                ],
                "dimensions": [
                    {
                        "entity": d.entity,
                        "key": d.key,
                        "sources": d.sources,
                        "attributes": d.attributes,
                        "reason": d.reason,
                    }
                    for d in s.dimensions
                ],
            }
            for s in model.subjects
        ],
        "conformed": [
            {
                "entity": c.entity,
                "key": c.key,
                "subjects": c.subjects,
                "reason": c.reason,
            }
            for c in model.conformed
        ],
        "unassigned": [
            {"entity": u.entity, "sources": u.sources, "reason": u.reason}
            for u in model.unassigned
        ],
    }
