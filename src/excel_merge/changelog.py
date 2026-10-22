"""Ändringslogg för datakällor.

Loggen beskriver ändringar i *datan*, inte i applikationen. Den svarar på
frågan "vad hände med källorna, och när?" och skrivs som JSON-radsformat
(NDJSON) så att den går att läsa både med ögat och med kod.

Händelser:

- ``source_added``   en källa finns i specen men har inte setts förut
- ``source_removed`` en källa har setts förut men finns inte i specen längre
- ``source_changed`` innehållet har ett annat fingeravtryck än förra körningen
- ``source_unchanged`` innehållet är identiskt (endast om ``--verbose``)

Loggen jämför mot ett *tillstånd* (``state``) som håller senast kända
fingeravtryck per källa. Tillståndet är den lilla bokföringen; loggen är den
läsbara historiken. Att de är åtskilda gör att loggen kan läsas av människor
medan tillståndet kan läsas snabbt av nästa körning.

Tidsstämplar är UTC i ISO 8601. Tiden kan injiceras, så att testerna blir
deterministiska.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ADDED = "source_added"
REMOVED = "source_removed"
CHANGED = "source_changed"
UNCHANGED = "source_unchanged"
UNREADABLE = "source_unreadable"
RECOVERED = "source_recovered"

# Strukturhändelser: hur pipen själv förändras. Datan kan vara oförändrad
# samtidigt som en källa läggs till, byter nyckel eller stryks ur specen.
DECLARED = "source_declared"
UNDECLARED = "source_undeclared"
REDEFINED = "source_redefined"
ENTITY_DECLARED = "entity_declared"
ENTITY_UNDECLARED = "entity_undeclared"
ENTITY_REDEFINED = "entity_redefined"
BUILD_REDEFINED = "build_redefined"

# Mottagningshändelse: en fil har kommit in i systemet.
FILE_RECEIVED = "file_received"

# De tre slagen av händelser. Loggen är en enda ström, men varje rad tillhör
# ett slag, så att gränssnittet kan filtrera utan att känna till varje namn:
#   data      - innehållet i en källa har ändrats
#   structure - pipens uppbyggnad har ändrats (specen)
#   ingest    - en fil har tagits emot
DATA = "data"
STRUCTURE = "structure"
INGEST = "ingest"

KINDS = (DATA, STRUCTURE, INGEST)

DATA_EVENTS = (ADDED, REMOVED, CHANGED, UNCHANGED, UNREADABLE, RECOVERED)
STRUCTURE_EVENTS = (
    DECLARED,
    UNDECLARED,
    REDEFINED,
    ENTITY_DECLARED,
    ENTITY_UNDECLARED,
    ENTITY_REDEFINED,
    BUILD_REDEFINED,
)
INGEST_EVENTS = (FILE_RECEIVED,)

EVENT_TYPES = DATA_EVENTS + STRUCTURE_EVENTS + INGEST_EVENTS

# Slaget för varje händelsetyp. Används för att läsa en logg som skrevs innan
# fältet ``kind`` fanns: äldre rader saknar det och slaget härleds då ur namnet.
KIND_OF = {**{name: DATA for name in DATA_EVENTS},
           **{name: STRUCTURE for name in STRUCTURE_EVENTS},
           **{name: INGEST for name in INGEST_EVENTS}}


def kind_of(event: str) -> str:
    """Slaget för en händelse, med hänsyn till äldre rader utan ``kind``."""
    return KIND_OF.get(event, DATA)

# Hur mycket av fingeravtrycket som visas i loggen. Tillräckligt för att skilja
# två versioner åt, kort nog att loggen förblir läsbar.
_SHORT = 12


def _short(digest: str | None) -> str | None:
    if not digest:
        return None
    return digest.split(":", 1)[-1][:_SHORT]


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ChangeEvent:
    """En ändring i datat eller i pipens struktur, med tidpunkt och orsak."""

    timestamp: str
    event: str
    source: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return kind_of(self.event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "event": self.event,
            "source": self.source,
            **self.details,
        }

    def describe(self) -> str:
        """En läsbar rad för utskrift i terminalen."""
        if self.event == ADDED:
            return f"+ {self.source} tillagd ({self.details.get('rows', '?')} rader)"
        if self.event == REMOVED:
            reason = self.details.get("reason")
            suffix = f", {reason}" if reason else ""
            return f"- {self.source} borttagen (senast {self.details.get('last_seen', '?')}{suffix})"
        if self.event == CHANGED:
            parts = []
            if self.details.get("rows_before") is None:
                # Källan var oläsbar förra körningen; nu går den att läsa igen.
                return f"~ {self.source} läsbar igen ({self.details.get('rows', '?')} rader)"
            if self.details.get("rows_before") != self.details.get("rows"):
                parts.append(f"{self.details.get('rows_before')} -> {self.details.get('rows')} rader")
            added = self.details.get("columns_added") or []
            removed = self.details.get("columns_removed") or []
            if added:
                parts.append("nya kolumner: " + ", ".join(added))
            if removed:
                parts.append("borttagna kolumner: " + ", ".join(removed))
            if not parts:
                parts.append("innehållet har ändrats")
            return f"~ {self.source} ändrad ({'; '.join(parts)})"
        if self.event == UNREADABLE:
            return f"! {self.source} kunde inte läsas ({self.details.get('error', 'okänt fel')})"
        if self.event == RECOVERED:
            return f"✓ {self.source} läsbar igen ({self.details.get('rows', '?')} rader)"
        if self.event == DECLARED:
            return f"+ {self.source} inlagd i specen ({self._spec_summary()})"
        if self.event == UNDECLARED:
            return f"- {self.source} struken ur specen"
        if self.event == REDEFINED:
            changes = self.details.get("changes") or []
            return f"~ {self.source} omdefinierad ({'; '.join(changes) or 'ändrad'})"
        if self.event == ENTITY_DECLARED:
            return f"+ entiteten {self.source} tillagd ({self._spec_summary()})"
        if self.event == ENTITY_UNDECLARED:
            return f"- entiteten {self.source} borttagen ur specen"
        if self.event == ENTITY_REDEFINED:
            changes = self.details.get("changes") or []
            return f"~ entiteten {self.source} omdefinierad ({'; '.join(changes) or 'ändrad'})"
        if self.event == BUILD_REDEFINED:
            changes = self.details.get("changes") or []
            return f"~ bygget {self.source} omdefinierat ({'; '.join(changes) or 'ändrat'})"
        if self.event == FILE_RECEIVED:
            size = self.details.get("bytes")
            return f"↓ {self.source} togs emot ({size} byte)" if size is not None else f"↓ {self.source} togs emot"
        return f"= {self.source} oförändrad"

    def _spec_summary(self) -> str:
        """Kort sammanfattning av en spec-post, för läsbara rader."""
        parts = []
        if self.details.get("path"):
            parts.append(str(self.details["path"]))
        if self.details.get("sheet"):
            parts.append(f"flik {self.details['sheet']}")
        if self.details.get("entity"):
            parts.append(f"entitet {self.details['entity']}")
        return ", ".join(parts) or "okänt innehåll"


def diff_fingerprints(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Beskriv vad som skiljer två fingeravtryck åt, i mänskliga termer."""
    columns_before = list(before.get("columns") or [])
    columns_after = list(after.get("columns") or [])
    details: dict[str, Any] = {
        "fingerprint_before": _short(before.get("fingerprint")),
        "fingerprint_after": _short(after.get("fingerprint")),
        "rows_before": before.get("rows"),
        "rows": after.get("rows"),
    }
    added = [c for c in columns_after if c not in columns_before]
    removed = [c for c in columns_before if c not in columns_after]
    if added:
        details["columns_added"] = added
    if removed:
        details["columns_removed"] = removed
    return details


class ChangeLog:
    """Skriv och läs ändringsloggen, samt det tillstånd den jämför mot."""

    def __init__(self, log_path: Path, state_path: Path, verbose: bool = False):
        self.log_path = Path(log_path)
        self.state_path = Path(state_path)
        self.verbose = verbose

    # --- tillstånd ---

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"version": 1, "sources": {}}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Ett trasigt tillstånd ska inte stoppa flödet; hellre en ny baslinje.
            return {"version": 1, "sources": {}}
        if not isinstance(raw, dict) or "sources" not in raw:
            return {"version": 1, "sources": {}}
        return raw

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
        # Skriv till en temporär fil och byt namn, så att ett avbrott inte
        # lämnar ett halvskrivet tillstånd efter sig.
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    # --- logg ---

    def append(self, events: Iterable[ChangeEvent]) -> int:
        events = list(events)
        if not events:
            return 0
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return len(events)

    def read_events(self) -> list[dict[str, Any]]:
        if not self.log_path.is_file():
            return []
        events = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events


def detect_changes(
    current: dict[str, dict[str, Any]],
    state: dict[str, Any],
    timestamp: str,
    verbose: bool = False,
    unreadable: dict[str, str] | None = None,
    missing: dict[str, str] | None = None,
) -> list[ChangeEvent]:
    """Jämför nuvarande fingeravtryck mot tillståndet och beskriv skillnaderna.

    ``current`` är källnamn -> fingeravtryck (som dict). ``state`` är det
    sparade tillståndet med senast kända fingeravtryck. ``unreadable`` är
    källor som finns i specen men inte gick att läsa, med felmeddelandet.
    ``missing`` är källor vars fil eller flik inte finns, med orsaken.

    En källa som inte gick att läsa rapporteras som ``source_unreadable`` i
    stället för att avbryta hela körningen. Annars kunde bevakningen aldrig
    rapportera det mest intressanta av allt: att en källa försvunnit.

    En källa vars fil saknas behandlas som borttagen. Den finns inte längre, och
    ska därför inte finnas kvar i modellen - precis som om posten struktis ur
    specen. Den rapporteras som ``source_removed``, inte som oläsbar: skillnaden
    är att en trasig fil finns kvar medan en saknad fil är borta.
    """
    known: dict[str, Any] = dict(state.get("sources") or {})
    unreadable = unreadable or {}
    missing = missing or {}
    events: list[ChangeEvent] = []

    for name in sorted(current):
        after = current[name]
        before = known.get(name)
        if before is not None and before.get("unreadable_error"):
            # Källan gick inte att läsa förra körningen men gör det nu. Det ska
            # synas, annars påstår loggens sista rad att källan fortfarande är
            # trasig. Händelsen utfärdas även om innehållet är oförändrat.
            events.append(
                ChangeEvent(
                    timestamp,
                    RECOVERED,
                    name,
                    {"rows": after.get("rows"), "error_before": before.get("unreadable_error")},
                )
            )
        if before is None:
            events.append(
                ChangeEvent(timestamp, ADDED, name, {"rows": after.get("rows"), "columns": list(after.get("columns") or [])})
            )
        elif before.get("fingerprint") != after.get("fingerprint"):
            events.append(ChangeEvent(timestamp, CHANGED, name, diff_fingerprints(before, after)))
        elif verbose:
            events.append(ChangeEvent(timestamp, UNCHANGED, name, {"rows": after.get("rows")}))

    for name in sorted(unreadable):
        before = known.get(name) or {}
        # Logga bara övergången till oläsbar, inte varje körning medan felet
        # består. Annars fylls loggen av dubbletter om en fil ligger borta
        # länge. Ett ändrat felmeddelande är däremot en ny händelse.
        if before.get("unreadable_error") == unreadable[name]:
            continue
        events.append(
            ChangeEvent(timestamp, UNREADABLE, name, {"error": unreadable[name], "known": name in known})
        )

    # Borttagna: de som setts förut men varken går att läsa eller finns kvar.
    for name in sorted(set(known) - set(current) - set(unreadable)):
        details: dict[str, Any] = {"last_seen": known[name].get("last_seen", "okänt")}
        if name in missing:
            details["reason"] = "filen eller fliken saknas"
        events.append(ChangeEvent(timestamp, REMOVED, name, details))

    return events


def spec_snapshot(spec) -> dict[str, Any]:
    """En jämförbar bild av specens uppbyggnad.

    Fingeravtryck för data svarar på "har innehållet ändrats?". Den här bilden
    svarar på den andra frågan: "har pipens struktur ändrats?" - vilka källor som
    ingår, vilka nycklar de använder och vad byggena producerar.

    Bilden är avsiktligt läsbar JSON, inte en hash: när något ändrats ska loggen
    kunna säga *vad* som ändrats, inte bara att något gjort det.
    """
    return {
        "sources": {
            s.name: {
                "path": str(s.path),
                "sheet": s.sheet,
                "entity": s.entity,
                "columns": dict(s.columns),
                "dtypes": dict(s.dtypes),
                "relationships": [
                    {"to": r.to, "via": r.via, "cardinality": r.cardinality, "orphans": r.orphans}
                    for r in s.relationships
                ],
            }
            for s in spec.sources
        },
        "entities": {
            name: {"key": e.key, "description": e.description}
            for name, e in spec.entities.items()
        },
        "builds": {
            b.name: {
                "base": b.base,
                "include": list(b.include),
                "output": str(b.output),
                "sheet": b.sheet,
                "columns": list(b.columns) if b.columns else None,
            }
            for b in spec.builds
        },
    }


def _source_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Vad som skiljer två källposter åt, i mänskliga termer."""
    changes: list[str] = []
    for field, label in (("path", "sökväg"), ("sheet", "flik"), ("entity", "entitet")):
        if before.get(field) != after.get(field):
            changes.append(f"{label}: {before.get(field)} -> {after.get(field)}")

    columns_before = before.get("columns") or {}
    columns_after = after.get("columns") or {}
    for column in sorted(set(columns_after) - set(columns_before)):
        changes.append(f"kolumnen '{column}' tillagd -> {columns_after[column]}")
    for column in sorted(set(columns_before) - set(columns_after)):
        changes.append(f"kolumnen '{column}' borttagen")
    for column in sorted(set(columns_before) & set(columns_after)):
        if columns_before[column] != columns_after[column]:
            changes.append(f"kolumnen '{column}' mappas nu till '{columns_after[column]}'")

    for column in sorted(set(after.get("dtypes") or {}) - set(before.get("dtypes") or {})):
        changes.append(f"typ satt för '{column}': {(after.get('dtypes') or {})[column]}")
    for column in sorted(set(before.get("dtypes") or {}) - set(after.get("dtypes") or {})):
        changes.append(f"typ borttagen för '{column}'")

    def _rel_key(rel: dict[str, Any]) -> str:
        return f"{rel.get('to')}/{rel.get('via')}"

    rels_before = {_rel_key(r): r for r in (before.get("relationships") or [])}
    rels_after = {_rel_key(r): r for r in (after.get("relationships") or [])}
    for key in sorted(set(rels_after) - set(rels_before)):
        rel = rels_after[key]
        changes.append(
            f"relation till {rel.get('to')} via {rel.get('via')} tillagd "
            f"({rel.get('cardinality')}, orphans={rel.get('orphans')})"
        )
    for key in sorted(set(rels_before) - set(rels_after)):
        changes.append(f"relation till {rels_before[key].get('to')} via {rels_before[key].get('via')} borttagen")
    for key in sorted(set(rels_before) & set(rels_after)):
        old, new = rels_before[key], rels_after[key]
        if old.get("cardinality") != new.get("cardinality"):
            changes.append(
                f"kardinalitet för {new.get('via')}: {old.get('cardinality')} -> {new.get('cardinality')}"
            )
        if old.get("orphans") != new.get("orphans"):
            changes.append(f"orphans för {new.get('via')}: {old.get('orphans')} -> {new.get('orphans')}")
    return changes


def detect_structure_changes(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    timestamp: str,
) -> list[ChangeEvent]:
    """Jämför specens struktur mot senast kända bild och beskriv skillnaderna.

    Detta är den del av loggen som besvarar frågan "hur har datapipen förändrats
    över tid?" - till skillnad från datahändelserna, som bara säger att
    innehållet i en redan känd källa har ändrats.

    Saknas en tidigare bild (första körningen, eller en logg skriven innan
    strukturhändelserna fanns) rapporteras varje källa och entitet som inlagd.
    Det är riktigt: vi vet att de finns nu och har ingen tidigare kunskap.
    """
    previous = state.get("structure") or {}
    prev_sources = previous.get("sources") or {}
    prev_entities = previous.get("entities") or {}
    prev_builds = previous.get("builds") or {}

    now_sources = snapshot.get("sources") or {}
    now_entities = snapshot.get("entities") or {}
    now_builds = snapshot.get("builds") or {}

    events: list[ChangeEvent] = []

    for name in sorted(now_sources):
        after = now_sources[name]
        before = prev_sources.get(name)
        if before is None:
            events.append(ChangeEvent(timestamp, DECLARED, name, dict(after)))
        elif before != after:
            changes = _source_changes(before, after)
            if changes:
                events.append(ChangeEvent(timestamp, REDEFINED, name, {"changes": changes}))
    for name in sorted(set(prev_sources) - set(now_sources)):
        events.append(ChangeEvent(timestamp, UNDECLARED, name, {"last_known": prev_sources[name]}))

    for name in sorted(now_entities):
        after = now_entities[name]
        before = prev_entities.get(name)
        if before is None:
            events.append(ChangeEvent(timestamp, ENTITY_DECLARED, name, dict(after)))
        elif before != after:
            changes = []
            if before.get("key") != after.get("key"):
                changes.append(f"nyckel: {before.get('key')} -> {after.get('key')}")
            if before.get("description") != after.get("description"):
                changes.append("beskrivningen har ändrats")
            if changes:
                events.append(ChangeEvent(timestamp, ENTITY_REDEFINED, name, {"changes": changes}))
    for name in sorted(set(prev_entities) - set(now_entities)):
        events.append(ChangeEvent(timestamp, ENTITY_UNDECLARED, name, {"last_known": prev_entities[name]}))

    for name in sorted(now_builds):
        after = now_builds[name]
        before = prev_builds.get(name)
        if before is None:
            events.append(ChangeEvent(timestamp, BUILD_REDEFINED, name, {"changes": ["bygget tillagt"], **after}))
            continue
        if before == after:
            continue
        changes = []
        if before.get("base") != after.get("base"):
            changes.append(f"bas: {before.get('base')} -> {after.get('base')}")
        if before.get("include") != after.get("include"):
            changes.append(f"inkluderar: {before.get('include')} -> {after.get('include')}")
        if before.get("columns") != after.get("columns"):
            changes.append("utdatakolumnerna har ändrats")
        if before.get("output") != after.get("output") or before.get("sheet") != after.get("sheet"):
            changes.append("utdatafilen har ändrats")
        if changes:
            events.append(ChangeEvent(timestamp, BUILD_REDEFINED, name, {"changes": changes}))

    return events


def next_state(
    current: dict[str, dict[str, Any]],
    state: dict[str, Any],
    timestamp: str,
    unreadable: dict[str, str] | None = None,
    structure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bygg det nya tillståndet: källor som finns nu, med tidpunkt för senaste ändring.

    Källor som inte gick att läsa behåller sitt senaste kända fingeravtryck och
    märks med ``unreadable_at``. Att tappa dem vore fel: ett tillfälligt
    läsproblem skulle då radera historiken, och när filen kom tillbaka skulle
    den felaktigt rapporteras som helt ny.

    En källa vars fil eller flik saknas följer däremot inte med in i det nya
    tillståndet. Den finns inte längre, och då ska den inte finnas kvar i
    modellen - precis som om posten struktis ur specen. Kommer filen tillbaka
    rapporteras den därför som tillagd, inte som återställd.

    ``structure`` är specens bild. Den sparas i tillståndet så att nästa körning
    kan avgöra vad som ändrats i pipens uppbyggnad.
    """
    previous = dict(state.get("sources") or {})
    unreadable = unreadable or {}
    sources: dict[str, Any] = {}

    for name, fingerprint in current.items():
        entry = {
            "fingerprint": fingerprint.get("fingerprint"),
            "rows": fingerprint.get("rows"),
            "columns": list(fingerprint.get("columns") or []),
            "first_seen": previous.get(name, {}).get("first_seen", timestamp),
            "last_seen": timestamp,
        }
        if previous.get(name, {}).get("fingerprint") != fingerprint.get("fingerprint"):
            entry["last_changed"] = timestamp
        elif "last_changed" in previous.get(name, {}):
            entry["last_changed"] = previous[name]["last_changed"]
        sources[name] = entry

    for name in sorted(unreadable):
        entry = dict(previous.get(name) or {})
        if not entry:
            # Aldrig läst: vi vet att källan finns i specen men inget om innehållet.
            entry = {"fingerprint": None, "rows": None, "columns": [], "first_seen": timestamp}
        entry["last_seen"] = timestamp
        entry["unreadable_at"] = timestamp
        entry["unreadable_error"] = unreadable[name]
        sources[name] = entry

    result: dict[str, Any] = {"version": 1, "sources": sources, "updated_at": timestamp}
    if structure is not None:
        result["structure"] = structure
    elif "structure" in state:
        # Behåll senast kända struktur när anroparen inte har någon att ge oss.
        result["structure"] = state["structure"]
    return result
