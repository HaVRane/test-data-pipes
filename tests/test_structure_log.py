"""Tester för strukturhändelser i loggen.

Loggen beskriver inte bara *datat* utan också *pipens uppbyggnad*. Det är den
delen som gör att frågan "hur har dataflödet förändrats över tid?" går att
besvara i efterhand: när en källa lades till, när en nyckel byttes, när ett
bygge fick nya kolumner.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from excel_merge.changelog import (
    DATA,
    DECLARED,
    ENTITY_DECLARED,
    ENTITY_REDEFINED,
    ENTITY_UNDECLARED,
    REDEFINED,
    STRUCTURE,
    UNDECLARED,
    ChangeLog,
    detect_structure_changes,
    kind_of,
    next_state,
    spec_snapshot,
)
from excel_merge.relations import load_relation_spec
from excel_merge.watch import record_ingest, run_watch

SPEC = """\
version: 1
entities:
  customer:
    key: customer_id
    description: En kund.
  order:
    key: order_id
    description: En order.
sources:
  - name: customers
    path: customers.xlsx
    sheet: Customers
    entity: customer
    columns: {customer_id: customer_id, name: customer_name}
  - name: orders
    path: orders.xlsx
    sheet: Orders
    entity: order
    columns: {order_id: order_id, customer_id: customer_id}
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out/merged.xlsx
    sheet: Merged
    columns: [order_id, customer_id, customer_name]
"""


@pytest.fixture()
def spec_dir(tmp_path: Path) -> Path:
    import pandas as pd

    pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]}).to_excel(
        tmp_path / "customers.xlsx", index=False, sheet_name="Customers"
    )
    pd.DataFrame({"order_id": [10, 11], "customer_id": [1, 2]}).to_excel(
        tmp_path / "orders.xlsx", index=False, sheet_name="Orders"
    )
    (tmp_path / "relations.yaml").write_text(SPEC, encoding="utf-8")
    return tmp_path


def _state(spec_dir: Path, timestamp: str = "t1") -> dict:
    """Bygg ett tillstånd med en sparad strukturbild, som efter en första watch."""
    spec = load_relation_spec(spec_dir / "relations.yaml")
    snapshot = spec_snapshot(spec)
    return {"version": 1, "sources": {}, "structure": snapshot, "updated_at": timestamp}


def test_first_run_reports_every_source_and_entity_as_declared(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    events = detect_structure_changes(spec_snapshot(spec), {"sources": {}}, "t")
    by_event = {}
    for event in events:
        by_event.setdefault(event.event, []).append(event.source)
    assert sorted(by_event[DECLARED]) == ["customers", "orders"]
    assert sorted(by_event[ENTITY_DECLARED]) == ["customer", "order"]


def test_unchanged_structure_is_silent(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    state = _state(spec_dir)
    assert detect_structure_changes(spec_snapshot(spec), state, "t2") == []


def test_new_source_is_reported_as_declared(spec_dir):
    """Den händelse som saknades: en källa läggs in i pipen."""
    spec = load_relation_spec(spec_dir / "relations.yaml")
    state = _state(spec_dir)
    (spec_dir / "regions.xlsx").write_bytes(b"")
    updated = SPEC.replace(
        "  - name: orders",
        "  - name: regions\n"
        "    path: regions.xlsx\n"
        "    sheet: Regions\n"
        "    entity: customer\n"
        "    columns: {customer_id: customer_id, region: region}\n"
        "  - name: orders",
    )
    (spec_dir / "relations.yaml").write_text(updated, encoding="utf-8")
    new_spec = load_relation_spec(spec_dir / "relations.yaml")

    events = detect_structure_changes(spec_snapshot(new_spec), state, "t2")
    declared = [e.source for e in events if e.event == DECLARED]
    assert declared == ["regions"]


def test_struck_source_is_reported_as_undeclared(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    state = _state(spec_dir)
    # Ta bort order-posten. Bygget tas också bort, annars vore specen ogiltig
    # (ett bygge måste ha en källa för varje entitet det inkluderar).
    reduced = SPEC[: SPEC.index("builds:")]
    reduced = reduced.replace(
        "  - name: orders\n"
        "    path: orders.xlsx\n"
        "    sheet: Orders\n"
        "    entity: order\n"
        "    columns: {order_id: order_id, customer_id: customer_id}\n"
        "    relationships:\n"
        "      - to: customer\n"
        "        via: customer_id\n"
        "        cardinality: many_to_one\n",
        "",
    )
    (spec_dir / "relations.yaml").write_text(reduced, encoding="utf-8")
    new_spec = load_relation_spec(spec_dir / "relations.yaml")

    events = detect_structure_changes(spec_snapshot(new_spec), state, "t2")
    assert [e.source for e in events if e.event == UNDECLARED] == ["orders"]


def test_changed_key_is_reported_as_redefined(spec_dir):
    """Ett nyckelbyte är en strukturell ändring som måste synas."""
    spec = load_relation_spec(spec_dir / "relations.yaml")
    state = _state(spec_dir)
    updated = SPEC.replace(
        "    columns: {customer_id: customer_id, name: customer_name}",
        "    columns: {customer_id: customer_id, name: customer_name}\n    dtypes: {customer_id: int}",
    )
    (spec_dir / "relations.yaml").write_text(updated, encoding="utf-8")
    new_spec = load_relation_spec(spec_dir / "relations.yaml")

    events = detect_structure_changes(spec_snapshot(new_spec), state, "t2")
    redefined = [e for e in events if e.event == REDEFINED]
    assert [e.source for e in redefined] == ["customers"]
    assert any("typ" in change for change in redefined[0].details["changes"])


def test_changed_entity_key_is_reported(spec_dir):
    """Byter entiteten nyckel ska både entiteten och källan rapporteras."""
    spec = load_relation_spec(spec_dir / "relations.yaml")
    state = _state(spec_dir)
    updated = (
        SPEC.replace("  customer:\n    key: customer_id", "  customer:\n    key: kund_id")
        .replace("    columns: {customer_id: customer_id, name: customer_name}",
                 "    columns: {customer_id: kund_id, name: customer_name}")
    )
    (spec_dir / "relations.yaml").write_text(updated, encoding="utf-8")
    new_spec = load_relation_spec(spec_dir / "relations.yaml")

    events = detect_structure_changes(spec_snapshot(new_spec), state, "t2")
    redefined = [e for e in events if e.event == ENTITY_REDEFINED]
    assert [e.source for e in redefined] == ["customer"]
    assert any("customer_id -> kund_id" in c for c in redefined[0].details["changes"])


def test_removed_entity_is_reported(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    state = _state(spec_dir)
    snapshot = spec_snapshot(spec)
    snapshot["entities"].pop("order")

    events = detect_structure_changes(snapshot, state, "t2")
    assert [e.source for e in events if e.event == ENTITY_UNDECLARED] == ["order"]


def test_structure_survives_in_state_after_watch(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    log = ChangeLog(spec_dir / "state" / "log.ndjson", spec_dir / "state" / "state.json")
    run_watch(spec, log.log_path, log.state_path, timestamp="t1")
    assert log.load_state()["structure"]["sources"].keys() == {"customers", "orders"}


def test_second_watch_writes_no_structure_events(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    log = ChangeLog(spec_dir / "state" / "log.ndjson", spec_dir / "state" / "state.json")
    run_watch(spec, log.log_path, log.state_path, timestamp="t1")
    second = run_watch(spec, log.log_path, log.state_path, timestamp="t2")
    assert [e for e in second if e.kind == STRUCTURE] == []


def test_every_event_carries_a_kind(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    log = ChangeLog(spec_dir / "state" / "log.ndjson", spec_dir / "state" / "state.json")
    run_watch(spec, log.log_path, log.state_path, timestamp="t1")
    events = log.read_events()
    assert events
    assert all(e["kind"] in ("data", "structure", "ingest") for e in events)


def test_data_and_structure_share_one_stream(spec_dir):
    """Ett loggflöde, två slag - det var hela poängen."""
    spec = load_relation_spec(spec_dir / "relations.yaml")
    log = ChangeLog(spec_dir / "state" / "log.ndjson", spec_dir / "state" / "state.json")
    run_watch(spec, log.log_path, log.state_path, timestamp="t1")
    kinds = {e["kind"] for e in log.read_events()}
    assert kinds == {DATA, STRUCTURE}


def test_old_log_lines_without_kind_are_read_as_data():
    """En logg skriven innan fältet fanns ska fortfarande gå att läsa."""
    assert kind_of("source_added") == DATA
    assert kind_of("source_declared") == STRUCTURE
    assert kind_of("file_received") == "ingest"


def test_ingest_event_is_logged(tmp_path: Path):
    event = record_ingest(
        tmp_path / "log.ndjson", tmp_path / "state.json", "NyFil.xlsx",
        {"bytes": 1234}, timestamp="t",
    )
    assert event.kind == "ingest"
    assert event.event == "file_received"
    assert event.source == "NyFil.xlsx"
    lines = (tmp_path / "log.ndjson").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["bytes"] == 1234


def test_structure_events_are_readable(spec_dir):
    spec = load_relation_spec(spec_dir / "relations.yaml")
    events = detect_structure_changes(spec_snapshot(spec), {"sources": {}}, "t")
    for event in events:
        text = event.describe()
        assert event.source in text
        assert text.strip()


def test_state_without_structure_keeps_none(spec_dir):
    """next_state utan strukturbild ska inte hitta på en."""
    result = next_state({}, {"version": 1, "sources": {}}, "t")
    assert "structure" not in result


def test_state_keeps_previous_structure_when_not_given(spec_dir):
    previous = {"version": 1, "sources": {}, "structure": {"sources": {"a": {}}}}
    result = next_state({}, previous, "t")
    assert result["structure"] == {"sources": {"a": {}}}
