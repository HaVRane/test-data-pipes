"""Kärnan i ändringsbevakningen.

Både CLI:t och webbapplikationen anropar ``run_watch``. Det är avsiktligt: om
de hade varsin implementation skulle de kunna säga olika saker om samma data,
och då är loggen inte längre tillförlitlig. Här finns logiken på ett ställe.
"""

from __future__ import annotations

from pathlib import Path

from excel_merge.changelog import (
    FILE_RECEIVED,
    ChangeEvent,
    ChangeLog,
    detect_changes,
    detect_structure_changes,
    next_state,
    spec_snapshot,
    utc_now,
)
from excel_merge.fingerprint import fingerprint_frame
from excel_merge.io import SourceMissingError, SourceReadError, read_raw_sheet
from excel_merge.relations import RelationSpec


def fingerprint_sources(
    spec: RelationSpec,
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Fingeravtryck för varje källa i specen, läst från hela fliken.

    Hela fliken läses, inte bara de kolumner specen använder, så att även en
    ny kolumn som ingen pekat ut ännu upptäcks.

    Returnerar (fingeravtryck, oläsbara, saknade). En källa som inte går att
    läsa stoppar inte de andra. Det är avgörande: om en försvunnen fil avbröt
    hela körningen kunde bevakningen aldrig rapportera att filen försvunnit -
    den mest intressanta händelsen av alla.

    En källa vars fil eller flik saknas hamnar *inte* bland fingeravtrycken.
    Den finns inte längre, och behandlas därför som borttagen - precis som om
    posten struktis ur specen. En trasig fil är däremot kvar i specen och
    rapporteras som oläsbar, inte som borttagen.
    """
    result: dict[str, dict] = {}
    unreadable: dict[str, str] = {}
    missing: dict[str, str] = {}
    for source in spec.sources:
        try:
            frame = read_raw_sheet(source, spec.base_dir)
        except SourceMissingError as exc:
            # Saknad källa utelämnas. detect_changes ser den som borttagen.
            missing[source.name] = str(exc)
            continue
        except SourceReadError as exc:
            unreadable[source.name] = str(exc)
            continue
        result[source.name] = fingerprint_frame(frame).as_dict()
    return result, unreadable, missing


def run_watch(
    spec: RelationSpec,
    log_path: Path,
    state_path: Path,
    timestamp: str | None = None,
    verbose: bool = False,
) -> list[ChangeEvent]:
    """Jämför källorna mot senast kända tillstånd och skriv nya händelser.

    Två slag av ändringar upptäcks i samma svep: ändringar i *datat* (innehållet
    i en källa) och ändringar i *strukturen* (hur pipen är uppbyggd enligt
    specen). Båda hamnar i samma logg, åtskilda av fältet ``kind``.

    Returnerar händelserna som skrevs, så att anroparen kan visa dem.
    """
    log = ChangeLog(log_path, state_path, verbose=verbose)
    stamp = timestamp or utc_now()

    current, unreadable, missing = fingerprint_sources(spec)
    state = log.load_state()
    snapshot = spec_snapshot(spec)

    events = detect_changes(
        current, state, stamp, verbose=verbose, unreadable=unreadable, missing=missing
    )
    events.extend(detect_structure_changes(snapshot, state, stamp))

    log.append(events)
    log.save_state(next_state(current, state, stamp, unreadable=unreadable, structure=snapshot))
    return events


def record_ingest(
    log_path: Path,
    state_path: Path,
    file_name: str,
    details: dict | None = None,
    timestamp: str | None = None,
) -> ChangeEvent:
    """Logga att en fil tagits emot.

    Själva mottagandet är inte en ändring i datat - filen är ännu inte läst - men
    det är ögonblicket då en ny källa börjar sitt liv. Utan den raden går det
    inte att i efterhand se när en fil kom in i systemet.
    """
    log = ChangeLog(log_path, state_path)
    event = ChangeEvent(timestamp or utc_now(), FILE_RECEIVED, file_name, dict(details or {}))
    log.append([event])
    return event
