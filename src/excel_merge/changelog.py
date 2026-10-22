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

EVENT_TYPES = (ADDED, REMOVED, CHANGED, UNCHANGED)

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
    """En ändring i datat, med tidpunkt och orsak."""

    timestamp: str
    event: str
    source: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "event": self.event, "source": self.source, **self.details}

    def describe(self) -> str:
        """En läsbar rad för utskrift i terminalen."""
        if self.event == ADDED:
            return f"+ {self.source} tillagd ({self.details.get('rows', '?')} rader)"
        if self.event == REMOVED:
            return f"- {self.source} borttagen (senast {self.details.get('last_seen', '?')})"
        if self.event == CHANGED:
            parts = []
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
        return f"= {self.source} oförändrad"


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
) -> list[ChangeEvent]:
    """Jämför nuvarande fingeravtryck mot tillståndet och beskriv skillnaderna.

    ``current`` är källnamn -> fingeravtryck (som dict). ``state`` är det
    sparade tillståndet med senast kända fingeravtryck.
    """
    known: dict[str, Any] = dict(state.get("sources") or {})
    events: list[ChangeEvent] = []

    for name in sorted(current):
        after = current[name]
        before = known.get(name)
        if before is None:
            events.append(
                ChangeEvent(timestamp, ADDED, name, {"rows": after.get("rows"), "columns": list(after.get("columns") or [])})
            )
        elif before.get("fingerprint") != after.get("fingerprint"):
            events.append(ChangeEvent(timestamp, CHANGED, name, diff_fingerprints(before, after)))
        elif verbose:
            events.append(ChangeEvent(timestamp, UNCHANGED, name, {"rows": after.get("rows")}))

    for name in sorted(set(known) - set(current)):
        events.append(
            ChangeEvent(timestamp, REMOVED, name, {"last_seen": known[name].get("last_seen", "okänt")})
        )

    return events


def next_state(
    current: dict[str, dict[str, Any]],
    state: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    """Bygg det nya tillståndet: källor som finns nu, med tidpunkt för senaste ändring."""
    previous = dict(state.get("sources") or {})
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

    return {"version": 1, "sources": sources, "updated_at": timestamp}
