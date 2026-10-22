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
