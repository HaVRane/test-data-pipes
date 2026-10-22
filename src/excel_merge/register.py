"""Registrering av en ny datakälla i relationsspecen.

Fram till nu var specen bara läst. Den här modulen skriver till den, vilket är
ett medvetet steg: en uppladdad fil ska bli en källa i pipen utan att någon
redigerar YAML för hand.

Tre saker gör att det går att göra utan att kontraktet urholkas:

1. Skrivningen är *kirurgisk*. Kommentarerna i specen är dess dokumentation och
   bevaras. Filen skrivs atomiskt, så ett avbrott lämnar inte en halv spec.
2. Den nya posten *valideras* innan den sparas, genom att hela specen laddas om.
   En ogiltig post skrivs aldrig.
3. Förslaget är *härlett ur datan*: entitetsnamn, nyckel och kolumnmappning
   kommer från profileringen, inte från gissningar. Kopplingen till en befintlig
   entitet föreslås bara när en nyckel faktiskt matchar.

Det sista är den viktiga avvägningen. Att gissa en koppling vore farligt - en
felaktig relation ger ett tyst felaktigt bygge. Därför läggs en källa till
*utan* relation om ingen säker koppling hittas, och blir då en isolerad nod som
syns i kartan. En agent eller människa kan sedan bekräfta relationen, och just
den ändringen loggas som en strukturell ändring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from excel_merge.io import SourceReadError, read_raw_sheet
from excel_merge.joins import looks_like_measure, rank_join_candidates
from excel_merge.profile import column_stats
from excel_merge.relations import RelationSpecError, load_relation_spec


class RegistrationError(RuntimeError):
    """Källan kunde inte registreras i specen."""


def _yaml() -> YAML:
    """En YAML-läsare som bevarar kommentarer och originalets stil."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def slug(text: str) -> str:
    """Gör ett namn till ett användbart käll- eller entitetsnamn."""
    cleaned = "".join(c if c.isalnum() else "_" for c in text.strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "kalla"


def suggest_source_name(path: Path, sheet: str, taken: set[str]) -> str:
    """Föreslå ett unikt källnamn ur filnamn och flik."""
    base = slug(path.stem)
    if base not in taken:
        return base
    combined = slug(f"{path.stem}_{sheet}")
    if combined not in taken:
        return combined
    suffix = 2
    while f"{combined}_{suffix}" in taken:
        suffix += 1
    return f"{combined}_{suffix}"


def _column_mapping(frame) -> dict[str, str]:
    """Mappa varje kolumn till ett namn i utdata.

    Namnen normaliseras till gemener med understreck, så att samma begrepp i två
    filer får samma namn. ``Customer ID`` och ``customer_id`` blir båda
    ``customer_id``, vilket är vad som gör att kopplingen kan hittas.

    Två kolumner kan normaliseras till samma namn (``Belopp`` och ``belopp``).
    Den andra får då en siffra, så att ingen kolumn tyst skriver över en annan.
    """
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for column in frame.columns:
        name = slug(str(column))
        candidate, suffix = name, 2
        while candidate in used:
            candidate = f"{name}_{suffix}"
            suffix += 1
        used.add(candidate)
        mapping[str(column)] = candidate
    return mapping


def candidate_keys(frame, mapping: dict[str, str]) -> list[str]:
    """Kolumner som kan identifiera en rad: unika och utan nollvärden.

    Kolumner vars namn antyder ett mått eller en tidpunkt väljs bort - ett belopp
    kan vara unikt av en slump utan att identifiera en rad.
    """
    found: list[tuple[int, str]] = []
    for original, output in mapping.items():
        if looks_like_measure(str(original)):
            continue
        stats = column_stats(frame[original], name=output)
        if not stats.is_candidate_key:
            continue
        priority = 0 if re.search(r"(^|_)(id|nr|nummer|kod|code|key)$", output) else 1
        found.append((priority, output))
    return [name for _, name in sorted(found)]


def entity_of_key(key: str) -> str:
    """Entitetsnamnet ur nyckelns rot: ``supplier_id`` -> ``supplier``."""
    return slug(re.sub(r"_(id|nr|nummer|kod|code|key)$", "", key) or key)


def _match_existing_entity(spec, frame, mapping: dict[str, str]):
    """Hitta en befintlig entitet som den nya källan säkert kan kopplas till.

    Kopplingen söks i *alla* kolumner, inte bara källans egen nyckel: en
    leverantörstabell har ``supplier_id`` som identitet men ``customer_id`` som
    referens till kundentiteten.

    En relation läggs bara till när nycklarna faktiskt matchar utan föräldralösa
    rader. Att gissa vore värre än att avstå: en felaktig relation ger ett tyst
    felaktigt bygge, medan en utebliven relation bara syns som en isolerad nod i
    kartan.
    """
    from excel_merge.io import read_sheet

    for source in spec.sources:
        entity = spec.entities.get(source.entity)
        if entity is None:
            continue
        try:
            existing = read_sheet(source, spec.base_dir)
        except SourceReadError:
            continue
        if entity.key not in existing.columns:
            continue

        candidates = rank_join_candidates(frame, existing, min_coverage=0.0)
        for candidate in candidates:
            if candidate.verdict != "rekommenderad":
                continue
            if candidate.right_column != entity.key:
                continue
            # Den nya källans nyckel finns inte hos den befintliga entiteten.
            # Det kan vara riktigt, men det är ett beslut som ska bekräftas.
            if candidate.comparison.orphans_left:
                continue
            return source.entity, candidate
    return None


@dataclass
class Registration:
    """Resultatet av en registrering, för visning och loggning."""

    name: str
    entity: str
    key: str
    sheet: str
    path: str
    columns: dict[str, str]
    relationship_to: str | None = None
    relationship_via: str | None = None
    cardinality: str | None = None

    def as_details(self) -> dict:
        details: dict = {
            "path": self.path,
            "sheet": self.sheet,
            "entity": self.entity,
            "key": self.key,
            "columns": dict(self.columns),
        }
        if self.relationship_to:
            details["relationship"] = {
                "to": self.relationship_to,
                "via": self.relationship_via,
                "cardinality": self.cardinality,
            }
        return details


def register_source(
    spec_path: Path,
    file_path: Path,
    sheet: str,
    *,
    name: str | None = None,
    entity: str | None = None,
    key: str | None = None,
    connect: bool = True,
) -> Registration:
    """Lägg till en flik som datakälla i specen och spara.

    ``connect`` styr om en koppling till en befintlig entitet får föreslås. Den
    läggs bara till när nycklarna matchar säkert; annars blir källan isolerad.

    Specen laddas om efter skrivningen. En post som inte validerar skrivs aldrig,
    och felet når anroparen i stället för att bli en tyst trasig pipeline.
    """
    spec_path = Path(spec_path)
    spec = load_relation_spec(spec_path)

    # En källa är en flik i en fil. Vi läser den som den är, utan projektion.
    from types import SimpleNamespace

    probe = SimpleNamespace(name="ny", path=file_path, sheet=sheet, required_input_columns=[],
                            columns={}, dtypes={})
    try:
        frame = read_raw_sheet(probe, Path.cwd())
    except SourceReadError as exc:
        raise RegistrationError(str(exc)) from exc

    if frame.empty and not list(frame.columns):
        raise RegistrationError(f"fliken '{sheet}' i {file_path.name} innehåller inga kolumner")

    mapping = _column_mapping(frame)
    taken = {s.name for s in spec.sources}
    source_name = name or suggest_source_name(Path(file_path), sheet, taken)
    if source_name in taken:
        raise RegistrationError(f"det finns redan en källa som heter '{source_name}'")

    # Ordningen är viktig: kopplingen bestäms *före* egennyckeln. En tabell med
    # både supplier_id och customer_id ska bli entiteten "supplier" med en
    # koppling till "customer" - inte ännu en källa för "customer".
    relationship = _match_existing_entity(spec, frame, mapping) if connect and entity is None else None
    foreign = mapping[relationship[1].left_column] if relationship else None

    keys = candidate_keys(frame, mapping)
    own = [k for k in keys if k != foreign]

    if relationship and not own:
        # Den enda nyckeln är referensen till en befintlig entitet. Då är denna
        # flik ännu en källa för samma entitet - inte en ny entitet som pekar på
        # den. Referensen till sig själv är ingen relation.
        entity_name = entity or relationship[0]
        key_column = key or foreign
        relationship = None
        row_key = None
    elif own:
        derived_key = own[0]
        entity_name = entity or entity_of_key(derived_key)
        key_column = key or derived_key
        row_key = None
    else:
        # Ingen kolumn duger som nyckel. Fliken får en radnyckel i stället för
        # att lämnas utanför: kravet är att varje fil blir en källa, och en källa
        # utan nyckel kan varken kopplas eller byggas med.
        derived_key = f"{slug(sheet)}_rad"
        entity_name = entity or slug(sheet)
        key_column = key or derived_key
        row_key = derived_key

    # --- skriv ---
    # Posterna byggs som fristående block och sätts in på rätt rad. Att lägga
    # dem i det inlästa dokumentet och skriva om hela filen vore enklare, men
    # ruamel fäster sektionskommentarerna på sektionens *sista* post. En ny post
    # skulle då hamna under fel rubrik och diffen bli missvisande. Textuell
    # insättning rör bara de rader som faktiskt tillkommer.
    yaml = _yaml()
    original_text = spec_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    structure = yaml.load(original_text)

    new_entity = entity_name not in structure["entities"]

    source_entry = CommentedMap()
    source_entry["name"] = source_name
    source_entry["path"] = _relative_to_spec(file_path, spec_path)
    source_entry["sheet"] = sheet
    source_entry["entity"] = entity_name
    if row_key:
        source_entry["row_key"] = row_key

    columns = CommentedMap()
    for original, output in mapping.items():
        columns[original] = output
    source_entry["columns"] = columns

    if relationship is not None:
        to_entity, candidate = relationship
        rel = CommentedMap()
        rel["to"] = to_entity
        # Specen arbetar med de mappade kolumnnamnen, inte originalets.
        rel["via"] = mapping[candidate.left_column]
        # many_to_one är den säkra läsningen av en referens till en befintlig
        # entitet: flera rader i den nya källan kan peka på samma entitetsrad.
        # Att sätta kardinaliteten efter hur datan råkade se ut i just detta
        # utdrag vore fel - se docs/relations.md. many_to_one validerar dessutom
        # oavsett om nyckeln råkar vara unik i urvalet.
        rel["cardinality"] = "many_to_one"
        rel["orphans"] = "keep"
        rel.yaml_add_eol_comment("maskinellt föreslagen - bekräfta mot verksamheten", "cardinality")
        rels = CommentedSeq()
        rels.append(rel)
        source_entry["relationships"] = rels

    # Insättningen sker nedifrån och upp: först källposten (vid 'builds'), sedan
    # entiteten (vid 'sources'). Då förskjuts inte radnumren för det som redan
    # satts in.
    source_block = _render(yaml, _as_sequence(source_entry))
    lines = _insert_before_section(lines, structure, "builds", source_block)
    if new_entity:
        entity_block = _render(yaml, _as_mapping(entity_name, key_column, file_path))
        # Entiteten ligger inuti 'entities', så blocket måste dras in ett steg.
        entity_block = ["  " + line if line else line for line in entity_block]
        lines = _insert_before_section(lines, structure, "sources", entity_block)
    _write_spec(spec_path, "\n".join(lines) + "\n")

    # --- validera ---
    try:
        load_relation_spec(spec_path)
    except RelationSpecError as exc:
        # En spec som inte validerar får aldrig ligga kvar på disk.
        spec_path.write_text(original_text, encoding="utf-8")
        raise RegistrationError(
            f"den nya posten gjorde specen ogiltig och skrevs därför inte: {exc}"
        ) from exc

    return Registration(
        name=source_name,
        entity=entity_name,
        key=key_column,
        sheet=sheet,
        path=str(source_entry["path"]),
        columns=mapping,
        relationship_to=relationship[0] if relationship else None,
        relationship_via=mapping[relationship[1].left_column] if relationship else None,
        cardinality="many_to_one" if relationship else None,
    )


def _render(yaml: YAML, node) -> list[str]:
    """Rendera ett YAML-block till rader, utan avslutande tomrad."""
    buffer = StringIO()
    yaml.dump(node, buffer)
    return buffer.getvalue().rstrip("\n").splitlines()


def _as_sequence(entry: CommentedMap) -> CommentedSeq:
    """Linda in en post i en sekvens, så att den renderas med listindrag."""
    seq = CommentedSeq()
    seq.append(entry)
    return seq


def _as_mapping(name: str, key: str, file_path: Path) -> CommentedMap:
    mapping = CommentedMap()
    body = CommentedMap()
    body["key"] = key
    body["description"] = f"En rad per {key} i {Path(file_path).name}."
    mapping[name] = body
    return mapping


def _insert_before_section(
    lines: list[str], structure, section: str, block: list[str]
) -> list[str]:
    """Sätt in ett block sist i föregående sektion, före ``section``.

    Rubrikkommentaren ovanför en sektion hör till sektionen. Insättningen sker
    därför ovanför kommentaren, inte mellan kommentaren och sektionsnyckeln.
    """
    start = structure.lc.data[section][0]
    insert_at = start
    while insert_at > 0 and (lines[insert_at - 1].strip() == ""
                             or lines[insert_at - 1].lstrip().startswith("#")):
        insert_at -= 1
    # Blankraden före nästa sektion finns ofta redan; lägg inte till en till.
    separator = [] if lines[insert_at].strip() == "" else [""]
    return lines[:insert_at] + block + separator + lines[insert_at:]


def _relative_to_spec(file_path: Path, spec_path: Path) -> str:
    """Sökvägen som specen ska ange, relativ till specens katalog.

    Specen ligger i ``config/`` och datat i ``data/``, så sökvägen blir
    ``../data/...``. Relativt är rätt val: projektet ska kunna flyttas utan att
    specen pekar fel.
    """
    import os

    resolved = Path(file_path).resolve()
    base = Path(spec_path).resolve().parent
    try:
        return Path(os.path.relpath(resolved, base)).as_posix()
    except ValueError:  # olika enheter på Windows
        return str(resolved)


def _write_spec(spec_path: Path, text: str) -> None:
    """Skriv specen atomiskt, så ett avbrott inte lämnar en halv fil."""
    import os

    temporary = spec_path.with_suffix(spec_path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, spec_path)
