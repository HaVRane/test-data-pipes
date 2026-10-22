"""Kärnan i ändringsbevakningen.

Både CLI:t och webbapplikationen anropar ``run_watch``. Det är avsiktligt: om
de hade varsin implementation skulle de kunna säga olika saker om samma data,
och då är loggen inte längre tillförlitlig. Här finns logiken på ett ställe.
"""

from __future__ import annotations

from pathlib import Path

from excel_merge.changelog import (
    ChangeEvent,
    ChangeLog,
    detect_changes,
    next_state,
    utc_now,
)
from excel_merge.fingerprint import fingerprint_frame
from excel_merge.io import SourceReadError, read_raw_sheet
from excel_merge.relations import RelationSpec


def fingerprint_sources(spec: RelationSpec) -> tuple[dict[str, dict], dict[str, str]]:
    """Fingeravtryck för varje källa i specen, läst från hela fliken.

    Hela fliken läses, inte bara de kolumner specen använder, så att även en
    ny kolumn som ingen pekat ut ännu upptäcks.

    Returnerar (fingeravtryck, oläsbara). En källa som inte går att läsa
    stoppar inte de andra. Det är avgörande: om en försvunnen fil avbröt hela
    körningen kunde bevakningen aldrig rapportera att filen försvunnit - den
    mest intressanta händelsen av alla.
    """
    result: dict[str, dict] = {}
    unreadable: dict[str, str] = {}
    for source in spec.sources:
        try:
            frame = read_raw_sheet(source, spec.base_dir)
        except SourceReadError as exc:
            unreadable[source.name] = str(exc)
            continue
        result[source.name] = fingerprint_frame(frame).as_dict()
    return result, unreadable


def run_watch(
    spec: RelationSpec,
    log_path: Path,
    state_path: Path,
    timestamp: str | None = None,
    verbose: bool = False,
) -> list[ChangeEvent]:
    """Jämför källorna mot senast kända tillstånd och skriv nya händelser.

    Returnerar händelserna som skrevs, så att anroparen kan visa dem.
    """
    log = ChangeLog(log_path, state_path, verbose=verbose)
    stamp = timestamp or utc_now()

    current, unreadable = fingerprint_sources(spec)
    state = log.load_state()
    events = detect_changes(current, state, stamp, verbose=verbose, unreadable=unreadable)

    log.append(events)
    log.save_state(next_state(current, state, stamp, unreadable=unreadable))
    return events
