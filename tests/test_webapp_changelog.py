"""End-to-end-tester för ändringsloggen och uppladdningen, mot en riktig server."""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from webapp import Handler  # noqa: E402

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

KEY = "testnyckel"


@pytest.fixture
def server(tmp_path):
    data = tmp_path / "data" / "isa"
    data.mkdir(parents=True)
    customers = data / "customers.xlsx"
    orders = data / "orders.xlsx"
    pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]}).to_excel(
        customers, index=False, sheet_name="Customers")
    pd.DataFrame({"order_id": [10, 11], "customer_id": [1, 2]}).to_excel(
        orders, index=False, sheet_name="Orders")
    regions = data / "regions.xlsx"
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

    handler = type("H", (Handler,), {
        "data_dir": data,
        "key": KEY,
        "spec_path": spec,
        "log_path": tmp_path / "state" / "changelog.ndjson",
        "state_path": tmp_path / "state" / "sources.json",
    })
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield {
        "base": f"http://127.0.0.1:{httpd.server_address[1]}",
        "data": data,
        "tmp": tmp_path,
        "spec": spec,
    }
    httpd.shutdown()
    httpd.server_close()


def get(server, path):
    with urllib.request.urlopen(f"{server['base']}{path}?key={KEY}") as response:
        return json.loads(response.read())


def post(server, path):
    request = urllib.request.Request(f"{server['base']}{path}?key={KEY}", method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def upload(server, name: str, data: bytes):
    """Ladda upp en fil via /upload, som webbsidan gör."""
    request = urllib.request.Request(
        f"{server['base']}/upload?key={KEY}",
        method="POST",
        data=data,
        headers={"X-Filename": name},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _workbook_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"kund_id": [1, 2], "namn": ["A", "B"]}).to_excel(
            writer, sheet_name="Kunder", index=False
        )
    return buffer.getvalue()


def test_upload_lands_in_the_data_directory_the_spec_reads(server):
    """Filen ska hamna i samma katalog som appen läser, inte i en sidokatalog."""
    status, payload = upload(server, "nya_kunder.xlsx", _workbook_bytes())
    assert status == 200, payload
    assert payload["success"] is True
    assert (server["data"] / "nya_kunder.xlsx").is_file()


def test_uploaded_file_shows_up_as_a_source_without_directory_or_extension(server):
    upload(server, "nya_kunder.xlsx", _workbook_bytes())
    books = get(server, "/sources")
    entry = next(b for b in books if b["name"] == "nya_kunder")
    assert entry["type"] == "Excel"
    assert entry["sheets"][0]["name"] == "Kunder"


def test_uploaded_file_becomes_a_source_in_the_spec(server):
    """Uppladdningen registrerar fliken, så filen syns i pipen direkt."""
    status, payload = upload(server, "nya_kunder.xlsx", _workbook_bytes())
    assert status == 200
    assert payload.get("registration_error") is None, payload
    assert payload["source"]["sheet"] == "Kunder"
    assert "nya_kunder" in server["spec"].read_text(encoding="utf-8")


def test_upload_rejects_disallowed_file_type(server):
    status, payload = upload(server, "elak.sh", b"#!/bin/sh\n")
    assert status == 400
    assert "filtypen" in payload["detail"]


def test_changelog_endpoint_is_empty_before_first_watch(server):
    payload = get(server, "/changelog")
    assert payload["events"] == []
    assert payload["sources"] == []


def test_watch_endpoint_creates_baseline(server):
    status, payload = post(server, "/watch")
    assert status == 200
    # Baslinjen består av tre datahändelser (källorna) och strukturhändelserna
    # för specen. Här avses datahändelserna.
    data_events = [e for e in payload["new_events"] if e["kind"] == "data"]
    assert len(data_events) == 3
    kinds = [e["event"] for e in data_events]
    assert kinds == ["source_added"] * 3
    assert sorted(payload["sources"]) == ["customers", "orders", "regions"]


def test_changelog_endpoint_returns_events_newest_first(server):
    post(server, "/watch")

    customers = server["data"] / "customers.xlsx"
    frame = pd.read_excel(customers, sheet_name="Customers")
    frame.loc[len(frame)] = [3, "C"]
    frame.to_excel(customers, index=False, sheet_name="Customers")

    post(server, "/watch")
    payload = get(server, "/changelog")
    events = payload["events"]
    assert events[0]["event"] == "source_changed"
    assert events[0]["source"] == "customers"
    assert events[0]["rows_before"] == 2
    assert events[0]["rows"] == 3
    # Nyast först
    assert events[-1]["event"] == "source_added"


def test_second_watch_writes_nothing(server):
    post(server, "/watch")
    status, payload = post(server, "/watch")
    assert status == 200
    assert payload["events_written"] == 0
    assert payload["new_events"] == []


def test_watch_reports_removed_source(server):
    post(server, "/watch")
    # regions används inte av något bygge, så specen förblir giltig.
    text = server["spec"].read_text(encoding="utf-8")
    head, _, _ = text.partition("  - name: regions")
    server["spec"].write_text(head + "builds:" + text.split("builds:", 1)[1], encoding="utf-8")
    status, payload = post(server, "/watch")
    assert status == 200
    removed = [e for e in payload["new_events"] if e["event"] == "source_removed"]
    assert [e["source"] for e in removed] == ["regions"]


def test_watch_without_spec_gives_readable_error(server):
    server["spec"].unlink()
    status, payload = post(server, "/watch")
    assert status == 400
    assert "hittades inte" in payload["detail"]


def test_watch_with_invalid_spec_gives_readable_error(server):
    server["spec"].write_text("version: 1\nsources: []\n", encoding="utf-8")
    status, payload = post(server, "/watch")
    assert status == 400
    assert "inte giltig" in payload["detail"]


def test_watch_with_broken_source_reports_it_without_crashing(server):
    """En trasig fil ska loggas som oläsbar, inte fälla hela bevakningen."""
    (server["data"] / "customers.xlsx").write_bytes(b"inte ett kalkylark")
    status, payload = post(server, "/watch")
    assert status == 200
    broken = [e for e in payload["new_events"] if e["event"] == "source_unreadable"]
    assert [e["source"] for e in broken] == ["customers"]
    assert "kunde inte läsas" in broken[0]["error"]
    # De andra källorna ska ändå ha lästs
    assert "orders" in payload["sources"]


def test_endpoints_require_key(server):
    for path in ("/changelog",):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{server['base']}{path}")
        assert exc.value.code == 403


def test_watch_requires_key(server):
    request = urllib.request.Request(f"{server['base']}/watch", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request)
    assert exc.value.code == 403


def test_changelog_state_is_reported(server):
    post(server, "/watch")
    payload = get(server, "/changelog")
    assert payload["state"]["customers"]["rows"] == 2
    assert "first_seen" in payload["state"]["customers"]


def test_web_and_cli_share_the_same_log(server):
    """Webben och CLI:t måste se samma sak om samma data.

    De anropar samma kärna (watch.run_watch), så en ändring via webben ska
    synas direkt i CLI:ts logg.
    """
    from excel_merge.changelog import ChangeLog

    post(server, "/watch")
    log = ChangeLog(server["tmp"] / "state" / "changelog.ndjson",
                    server["tmp"] / "state" / "sources.json")
    via_file = [e["event"] for e in log.read_events()]
    via_web = [e["event"] for e in get(server, "/changelog")["events"]]
    assert via_file == list(reversed(via_web))
    data_events = [e for e in log.read_events() if e["kind"] == "data"]
    assert sorted(e["event"] for e in data_events) == ["source_added"] * 3
