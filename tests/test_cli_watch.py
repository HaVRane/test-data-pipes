"""Integrationstester för watch- och log-kommandona."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from excel_merge.cli import main

SPEC = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
  region:
    key: region_id
sources:
  - name: customers
    path: {customers}
    sheet: Customers
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
    relationships: []
  - name: orders
    path: {orders}
    sheet: Orders
    entity: order
    columns:
      order_id: order_id
      customer_id: customer_id
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
  - name: regions
    path: {regions}
    sheet: Regions
    entity: region
    columns:
      region_id: region_id
builds:
  - name: b
    base: customer
    include: [order]
    output: {output}
    sheet: Merged
"""


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    customers = tmp_path / "customers.xlsx"
    orders = tmp_path / "orders.xlsx"
    pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]}).to_excel(customers, index=False, sheet_name="Customers")
    pd.DataFrame({"order_id": [10, 11], "customer_id": [1, 2]}).to_excel(orders, index=False, sheet_name="Orders")
    regions = tmp_path / "regions.xlsx"
    pd.DataFrame({"region_id": ["N", "S"]}).to_excel(regions, index=False, sheet_name="Regions")
    spec = tmp_path / "relations.yaml"
    spec.write_text(
        SPEC.format(
            customers=customers.as_posix(),
            orders=orders.as_posix(),
            regions=regions.as_posix(),
            output=(tmp_path / "out" / "m.xlsx").as_posix(),
        ),
        encoding="utf-8",
    )
    return spec


def _watch(spec: Path, tmp_path: Path, *extra: str) -> int:
    return main([
        "watch", "--spec", str(spec),
        "--log", str(tmp_path / "state" / "log.ndjson"),
        "--state", str(tmp_path / "state" / "sources.json"),
        *extra,
    ])


def test_first_watch_reports_sources_as_added(spec_file, tmp_path, capsys):
    assert _watch(spec_file, tmp_path, "--timestamp", "2026-01-01T00:00:00+00:00") == 0
    out = capsys.readouterr().out
    assert "customers tillagd" in out
    assert "orders tillagd" in out
    assert "regions tillagd" in out

    events = [
        json.loads(line)
        for line in (tmp_path / "state" / "log.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert [e["event"] for e in events] == ["source_added"] * 3
    assert all(e["timestamp"] == "2026-01-01T00:00:00+00:00" for e in events)


def test_second_watch_reports_no_changes(spec_file, tmp_path, capsys):
    _watch(spec_file, tmp_path, "--timestamp", "2026-01-01T00:00:00+00:00")
    capsys.readouterr()
    _watch(spec_file, tmp_path, "--timestamp", "2026-01-02T00:00:00+00:00")
    assert "Inga ändringar" in capsys.readouterr().out


def test_rewriting_file_without_data_change_is_not_a_change(spec_file, tmp_path, capsys):
    """Excel skriver om filen vid varje sparning - det får inte larma."""
    _watch(spec_file, tmp_path, "--timestamp", "t1")
    capsys.readouterr()

    customers = tmp_path / "customers.xlsx"
    frame = pd.read_excel(customers, sheet_name="Customers")
    frame.to_excel(customers, index=False, sheet_name="Customers")

    _watch(spec_file, tmp_path, "--timestamp", "t2")
    assert "Inga ändringar" in capsys.readouterr().out


def test_changed_data_is_detected(spec_file, tmp_path, capsys):
    _watch(spec_file, tmp_path, "--timestamp", "t1")
    capsys.readouterr()

    customers = tmp_path / "customers.xlsx"
    frame = pd.read_excel(customers, sheet_name="Customers")
    frame.loc[len(frame)] = [3, "C"]
    frame.to_excel(customers, index=False, sheet_name="Customers")

    _watch(spec_file, tmp_path, "--timestamp", "t2")
    out = capsys.readouterr().out
    assert "customers ändrad" in out
    assert "2 -> 3" in out


def test_removed_source_is_detected(spec_file, tmp_path, capsys):
    _watch(spec_file, tmp_path, "--timestamp", "t1")
    capsys.readouterr()

    # Ta bort regions-källan, som inget bygge använder, så specen förblir giltig.
    text = spec_file.read_text(encoding="utf-8")
    head, _, _ = text.partition("  - name: regions")
    spec_file.write_text(head + "builds:" + text.split("builds:", 1)[1], encoding="utf-8")

    assert _watch(spec_file, tmp_path, "--timestamp", "t2") == 0
    out = capsys.readouterr().out
    assert "regions borttagen" in out


def test_verbose_logs_unchanged_sources(spec_file, tmp_path, capsys):
    _watch(spec_file, tmp_path, "--timestamp", "t1")
    capsys.readouterr()
    _watch(spec_file, tmp_path, "--timestamp", "t2", "--verbose")
    assert "oförändrad" in capsys.readouterr().out


def test_log_command_shows_newest_first(spec_file, tmp_path, capsys):
    _watch(spec_file, tmp_path, "--timestamp", "2026-01-01T00:00:00+00:00")
    capsys.readouterr()
    customers = tmp_path / "customers.xlsx"
    frame = pd.read_excel(customers, sheet_name="Customers")
    frame.loc[len(frame)] = [3, "C"]
    frame.to_excel(customers, index=False, sheet_name="Customers")
    _watch(spec_file, tmp_path, "--timestamp", "2026-02-01T00:00:00+00:00")
    capsys.readouterr()

    main(["log", "--log", str(tmp_path / "state" / "log.ndjson"),
          "--state", str(tmp_path / "state" / "sources.json")])
    out = capsys.readouterr().out
    assert out.index("2026-02-01") < out.index("2026-01-01")


def test_log_command_filters_by_event_and_source(spec_file, tmp_path, capsys):
    _watch(spec_file, tmp_path, "--timestamp", "t1")
    capsys.readouterr()
    main(["log", "--log", str(tmp_path / "state" / "log.ndjson"),
          "--state", str(tmp_path / "state" / "sources.json"), "--event", "source_added", "--source", "orders"])
    out = capsys.readouterr().out
    assert "orders" in out
    assert "customers" not in out


def test_log_command_without_log_is_friendly(spec_file, tmp_path, capsys):
    main(["log", "--log", str(tmp_path / "state" / "log.ndjson"),
          "--state", str(tmp_path / "state" / "sources.json")])
    assert "Ingen logg" in capsys.readouterr().out


def test_state_file_records_first_seen(spec_file, tmp_path):
    _watch(spec_file, tmp_path, "--timestamp", "2026-01-01T00:00:00+00:00")
    state = json.loads((tmp_path / "state" / "sources.json").read_text(encoding="utf-8"))
    assert state["sources"]["customers"]["first_seen"] == "2026-01-01T00:00:00+00:00"
    assert state["sources"]["customers"]["rows"] == 2
