"""Tester för ändringsloggen."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from excel_merge.changelog import (
    ADDED,
    CHANGED,
    REMOVED,
    UNCHANGED,
    ChangeEvent,
    ChangeLog,
    detect_changes,
    next_state,
)


def fp(digest: str, rows: int = 4, columns=("id",)) -> dict:
    return {"fingerprint": digest, "rows": rows, "columns": list(columns)}


def test_first_run_reports_all_sources_as_added():
    current = {"customers": fp("sha256:aaa"), "orders": fp("sha256:bbb")}
    events = detect_changes(current, {"sources": {}}, "2026-10-22T12:00:00+00:00")
    assert [e.event for e in events] == [ADDED, ADDED]
    assert [e.source for e in events] == ["customers", "orders"]
    assert all(e.timestamp == "2026-10-22T12:00:00+00:00" for e in events)


def test_unchanged_source_is_silent_by_default():
    state = {"sources": {"customers": {**fp("sha256:aaa"), "last_seen": "igår"}}}
    events = detect_changes({"customers": fp("sha256:aaa")}, state, "nu")
    assert events == []


def test_unchanged_source_is_reported_in_verbose_mode():
    state = {"sources": {"customers": {**fp("sha256:aaa"), "last_seen": "igår"}}}
    events = detect_changes({"customers": fp("sha256:aaa")}, state, "nu", verbose=True)
    assert [e.event for e in events] == [UNCHANGED]


def test_changed_content_is_detected():
    state = {"sources": {"customers": fp("sha256:aaa")}}
    events = detect_changes({"customers": fp("sha256:bbb")}, state, "nu")
    assert [e.event for e in events] == [CHANGED]


def test_changed_event_describes_row_difference():
    state = {"sources": {"customers": fp("sha256:aaa", rows=4)}}
    events = detect_changes({"customers": fp("sha256:bbb", rows=6)}, state, "nu")
    details = events[0].details
    assert details["rows_before"] == 4
    assert details["rows"] == 6


def test_changed_event_lists_new_and_removed_columns():
    state = {"sources": {"k": fp("sha256:aaa", columns=("id", "namn"))}}
    events = detect_changes({"k": fp("sha256:bbb", columns=("id", "epost"))}, state, "nu")
    assert events[0].details["columns_added"] == ["epost"]
    assert events[0].details["columns_removed"] == ["namn"]


def test_removed_source_is_detected():
    state = {"sources": {"gammal": {**fp("sha256:aaa"), "last_seen": "2026-01-01T00:00:00+00:00"}}}
    events = detect_changes({}, state, "nu")
    assert [e.event for e in events] == [REMOVED]
    assert events[0].source == "gammal"
    assert events[0].details["last_seen"] == "2026-01-01T00:00:00+00:00"


def test_added_and_removed_and_changed_together():
    state = {
        "sources": {
            "behall": fp("sha256:aaa"),
            "andrad": fp("sha256:bbb"),
            "borta": fp("sha256:ccc"),
        }
    }
    current = {"behall": fp("sha256:aaa"), "andrad": fp("sha256:ddd"), "ny": fp("sha256:eee")}
    events = detect_changes(current, state, "nu")
    by_event = {e.event: [] for e in events}
    for e in events:
        by_event[e.event].append(e.source)
    assert by_event[ADDED] == ["ny"]
    assert by_event[CHANGED] == ["andrad"]
    assert by_event[REMOVED] == ["borta"]


def test_state_records_first_seen_and_last_changed():
    state = {"sources": {}}
    new = next_state({"k": fp("sha256:aaa")}, state, "2026-01-01T00:00:00+00:00")
    assert new["sources"]["k"]["first_seen"] == "2026-01-01T00:00:00+00:00"
    assert new["sources"]["k"]["last_changed"] == "2026-01-01T00:00:00+00:00"

    changed = next_state({"k": fp("sha256:bbb")}, new, "2026-02-01T00:00:00+00:00")
    assert changed["sources"]["k"]["first_seen"] == "2026-01-01T00:00:00+00:00"
    assert changed["sources"]["k"]["last_changed"] == "2026-02-01T00:00:00+00:00"
    assert changed["sources"]["k"]["last_seen"] == "2026-02-01T00:00:00+00:00"

    unchanged = next_state({"k": fp("sha256:bbb")}, changed, "2026-03-01T00:00:00+00:00")
    assert unchanged["sources"]["k"]["last_changed"] == "2026-02-01T00:00:00+00:00"
    assert unchanged["sources"]["k"]["last_seen"] == "2026-03-01T00:00:00+00:00"


def test_removed_source_is_dropped_from_state():
    state = {"sources": {"gammal": fp("sha256:aaa"), "kvar": fp("sha256:bbb")}}
    new = next_state({"kvar": fp("sha256:bbb")}, state, "nu")
    assert set(new["sources"]) == {"kvar"}


def test_log_roundtrip(tmp_path: Path):
    log = ChangeLog(tmp_path / "log.ndjson", tmp_path / "state.json")
    log.append([
        ChangeEvent("2026-01-01T00:00:00+00:00", ADDED, "customers", {"rows": 4}),
        ChangeEvent("2026-02-01T00:00:00+00:00", CHANGED, "customers", {"rows": 6}),
    ])
    events = log.read_events()
    assert [e["event"] for e in events] == [ADDED, CHANGED]
    assert events[1]["rows"] == 6


def test_log_appends_do_not_overwrite_history(tmp_path: Path):
    log = ChangeLog(tmp_path / "log.ndjson", tmp_path / "state.json")
    log.append([ChangeEvent("t1", ADDED, "a", {})])
    log.append([ChangeEvent("t2", CHANGED, "a", {})])
    assert [e["event"] for e in log.read_events()] == [ADDED, CHANGED]


def test_state_survives_save_and_load(tmp_path: Path):
    log = ChangeLog(tmp_path / "log.ndjson", tmp_path / "state.json")
    state = next_state({"k": fp("sha256:aaa")}, {"sources": {}}, "2026-01-01T00:00:00+00:00")
    log.save_state(state)
    assert log.load_state() == state


def test_corrupt_state_does_not_crash(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{trasigt", encoding="utf-8")
    log = ChangeLog(tmp_path / "log.ndjson", state_path)
    assert log.load_state() == {"version": 1, "sources": {}}


def test_corrupt_log_line_is_skipped(tmp_path: Path):
    log_path = tmp_path / "log.ndjson"
    log_path.write_text('{"event":"source_added","source":"a"}\ntrasigt\n{"event":"source_removed","source":"b"}\n',
                        encoding="utf-8")
    log = ChangeLog(log_path, tmp_path / "state.json")
    assert len(log.read_events()) == 2


def test_state_write_is_atomic(tmp_path: Path):
    """Ingen temporärfil ska ligga kvar efter skrivning."""
    log = ChangeLog(tmp_path / "log.ndjson", tmp_path / "state.json")
    log.save_state(next_state({"k": fp("sha256:aaa")}, {"sources": {}}, "nu"))
    assert list(tmp_path.glob("*.tmp")) == []


def test_event_describe_is_readable():
    added = ChangeEvent("t", ADDED, "customers", {"rows": 4})
    assert "customers" in added.describe() and "tillagd" in added.describe()
    removed = ChangeEvent("t", REMOVED, "orders", {"last_seen": "2026-01-01"})
    assert "borttagen" in removed.describe()
    changed = ChangeEvent("t", CHANGED, "orders", {"rows_before": 4, "rows": 6})
    assert "4 -> 6" in changed.describe()


def test_unreadable_source_is_reported_not_removed():
    """En källa som inte gick att läsa är inte samma sak som en borttagen källa."""
    state = {"sources": {"trasig": {**fp("sha256:aaa"), "last_seen": "igår"}}}
    events = detect_changes({}, state, "nu", unreadable={"trasig": "filen hittades inte"})
    assert [e.event for e in events] == ["source_unreadable"]
    assert events[0].details["error"] == "filen hittades inte"
    assert events[0].details["known"] is True


def test_unreadable_source_does_not_hide_other_sources():
    """En trasig källa ska inte tysta de andra."""
    state = {"sources": {"trasig": fp("sha256:aaa"), "frisk": fp("sha256:bbb")}}
    events = detect_changes(
        {"frisk": fp("sha256:ccc")}, state, "nu", unreadable={"trasig": "fel"}
    )
    kinds = {e.source: e.event for e in events}
    assert kinds == {"trasig": "source_unreadable", "frisk": "source_changed"}


def test_unreadable_source_is_not_reported_as_removed():
    state = {"sources": {"trasig": fp("sha256:aaa")}}
    events = detect_changes({}, state, "nu", unreadable={"trasig": "fel"})
    assert "source_removed" not in [e.event for e in events]


def test_unreadable_source_keeps_last_known_fingerprint():
    """Ett tillfälligt läsproblem får inte radera historiken."""
    state = {"sources": {"trasig": {**fp("sha256:aaa", rows=7), "first_seen": "första"}}}
    new = next_state({}, state, "nu", unreadable={"trasig": "fel"})
    entry = new["sources"]["trasig"]
    assert entry["fingerprint"] == "sha256:aaa"
    assert entry["rows"] == 7
    assert entry["first_seen"] == "första"
    assert entry["unreadable_at"] == "nu"


def test_source_returning_after_unreadable_is_reported_as_recovered():
    """Kommer filen tillbaka ska det synas, men inte som en ny källa.

    Utan denna händelse skulle loggens sista rad påstå att källan fortfarande
    är trasig, trots att den är frisk.
    """
    state = {"sources": {"k": {**fp("sha256:aaa"), "first_seen": "första"}}}
    after_error = next_state({}, state, "t1", unreadable={"k": "fel"})
    events = detect_changes({"k": fp("sha256:aaa")}, after_error, "t2")
    assert [e.event for e in events] == ["source_recovered"]
    assert events[0].details["error_before"] == "fel"


def test_recovery_does_not_look_like_a_new_source():
    state = {"sources": {"k": {**fp("sha256:aaa"), "first_seen": "första"}}}
    after_error = next_state({}, state, "t1", unreadable={"k": "fel"})
    events = detect_changes({"k": fp("sha256:aaa")}, after_error, "t2")
    assert "source_added" not in [e.event for e in events]


def test_source_changed_while_unreadable_is_detected_on_return():
    """Ändras filen medan den är oläsbar ska både återkomst och ändring synas."""
    state = {"sources": {"k": fp("sha256:aaa")}}
    after_error = next_state({}, state, "t1", unreadable={"k": "fel"})
    events = detect_changes({"k": fp("sha256:bbb")}, after_error, "t2")
    assert [e.event for e in events] == ["source_recovered", "source_changed"]


def test_never_read_source_is_marked_as_known_false():
    events = detect_changes({}, {"sources": {}}, "nu", unreadable={"ny": "fel"})
    assert events[0].details["known"] is False
    assert events[0].event == "source_unreadable"


def test_unreadable_event_describe_is_readable():
    event = ChangeEvent("t", "source_unreadable", "orders", {"error": "filen hittades inte"})
    assert "orders" in event.describe()
    assert "kunde inte läsas" in event.describe()


def test_repeated_unreadable_is_logged_only_once():
    """En fil som ligger borta länge ska inte fylla loggen med dubbletter."""
    state = {"sources": {"trasig": fp("sha256:aaa")}}
    first = detect_changes({}, state, "t1", unreadable={"trasig": "filen hittades inte"})
    assert [e.event for e in first] == ["source_unreadable"]

    # Andra körningen: samma fel. Ingen ny händelse.
    after = next_state({}, state, "t1", unreadable={"trasig": "filen hittades inte"})
    second = detect_changes({}, after, "t2", unreadable={"trasig": "filen hittades inte"})
    assert second == []


def test_changed_error_message_is_a_new_event():
    state = {"sources": {"trasig": fp("sha256:aaa")}}
    after = next_state({}, state, "t1", unreadable={"trasig": "filen hittades inte"})
    events = detect_changes({}, after, "t2", unreadable={"trasig": "fliken finns inte"})
    assert [e.event for e in events] == ["source_unreadable"]
    assert events[0].details["error"] == "fliken finns inte"


def test_unreadable_error_is_cleared_when_source_returns():
    state = {"sources": {"k": fp("sha256:aaa")}}
    broken = next_state({}, state, "t1", unreadable={"k": "fel"})
    assert "unreadable_error" in broken["sources"]["k"]

    healed = next_state({"k": fp("sha256:aaa")}, broken, "t2")
    assert "unreadable_error" not in healed["sources"]["k"]
    assert "unreadable_at" not in healed["sources"]["k"]


def test_never_read_source_becoming_readable_is_described_clearly():
    """En källa som aldrig hunnit läsas ska säga 'läsbar igen', inte 'None -> 4'."""
    event = ChangeEvent("t", CHANGED, "orders", {"rows_before": None, "rows": 4})
    text = event.describe()
    assert "läsbar igen" in text
    assert "None" not in text


def test_recovered_event_describe_is_readable():
    event = ChangeEvent("t", "source_recovered", "orders", {"rows": 4})
    assert "orders" in event.describe()
    assert "läsbar igen" in event.describe()
