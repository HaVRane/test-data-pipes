"""Tester för webbapplikationen."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from webapp import (  # noqa: E402
    PAGE,
    build_column_report,
    collect_sources,
    safe_name,
)
from fixtures import build_sample_sources, write_workbook


def test_page_has_six_tabs_and_valid_markup():
    assert "{{" not in PAGE and "}}" not in PAGE
    for tab in (
        "Anslut datakälla",
        "Indata",
        "Kolumner och koppling",
        "Indatarelationer",
        "Ämnesområden",
        "Ändringslogg",
    ):
        assert tab in PAGE


def test_page_has_changelog_tab_wiring():
    assert 'data-tab="changelog"' in PAGE
    assert 'id="changelog"' in PAGE
    assert "loadChangelog" in PAGE
    assert 'id="watchButton"' in PAGE


def test_safe_name_still_rejects_traversal_and_bad_types():
    assert safe_name("../../etc/passwd.xlsx") == "passwd.xlsx"
    with pytest.raises(ValueError, match="filtypen"):
        safe_name("elak.sh")


def test_accepts_spreadsheet_names():
    assert safe_name("customers.xlsx") == "customers.xlsx"
    assert safe_name("Min Fil 2024.XLSX") == "Min Fil 2024.XLSX"
    assert safe_name("data.csv") == "data.csv"


def test_strips_directory_components():
    # Katalogtraversering ska aldrig kunna ske
    assert safe_name("../../etc/passwd.xlsx") == "passwd.xlsx"
    assert safe_name("/tmp/evil.xlsx") == "evil.xlsx"
    assert safe_name("a/b/c.xlsx") == "c.xlsx"


def test_rejects_disallowed_suffixes():
    for bad in ("script.sh", "program.py", "bild.png", "arkiv.zip"):
        with pytest.raises(ValueError, match="filtypen"):
            safe_name(bad)


def test_rejects_hidden_and_empty_names():
    with pytest.raises(ValueError, match="ogiltigt"):
        safe_name(".bashrc")
    with pytest.raises(ValueError, match="ogiltigt"):
        safe_name("")
    with pytest.raises(ValueError, match="filtypen"):
        safe_name("utan_andelse")


def test_collect_sources_lists_workbooks_and_sheets(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    build_sample_sources(inbox)
    sources = collect_sources(tmp_path, inbox)
    names = [s["path"] for s in sources]
    assert any("customers.xlsx" in n for n in names)
    customers = next(s for s in sources if "customers" in s["path"])
    assert customers["sheets"][0]["name"] == "Customers"
    assert customers["sheets"][0]["rows"] == 4


def test_collect_sources_ignores_non_spreadsheets(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "anteckning.txt").write_text("nej", encoding="utf-8")
    (inbox / "README.md").write_text("nej", encoding="utf-8")
    assert collect_sources(tmp_path, inbox) == []


def test_collect_sources_survives_corrupt_file(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "trasig.xlsx").write_bytes(b"detta ar inte ett kalkylark")
    build_sample_sources(inbox)
    sources = collect_sources(tmp_path, inbox)
    broken = next(s for s in sources if "trasig" in s["path"])
    assert broken["sheets"] == []
    assert "error" in broken


def test_column_report_lists_columns_and_candidates(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    build_sample_sources(inbox)
    report = build_column_report(tmp_path, inbox)

    assert len(report["sources"]) == 2
    customers = next(s for s in report["sources"] if s["sheet"] == "Customers")
    column_names = [c["name"] for c in customers["columns"]]
    assert "customer_id" in column_names
    assert any(c["candidate_key"] for c in customers["columns"] if c["name"] == "customer_id")

    assert len(report["pairs"]) == 1
    pair = report["pairs"][0]
    assert pair["candidates"], "customer_id ska hittas som kandidat"
    best = pair["candidates"][0]
    assert best["left_column"] == "customer_id"
    assert best["verdict"] in {"rekommenderad", "möjlig"}
    assert "cardinality" in best["comparison"]
    assert "to:" in best["spec_entry"]
    # entitetsnamn, inte filsökväg, så utkastet kan klistras in i specen
    assert "/" not in best["spec_entry"].split("to:")[1].splitlines()[0]


def test_column_report_ranks_id_over_date(tmp_path):
    """Datumkolumn med identiska värden får inte vinna över id-kolumnen."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    write_workbook(inbox / "a.xlsx", {"A": pd.DataFrame({"datum": dates, "id": [1, 2, 3]})})
    write_workbook(inbox / "b.xlsx", {"B": pd.DataFrame({"datum": dates, "id": [1, 2, 3]})})
    report = build_column_report(tmp_path, inbox)
    best = report["pairs"][0]["candidates"][0]
    assert best["left_column"] == "id"


def test_column_report_handles_single_source(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    build_sample_sources(inbox)
    (inbox / "orders.xlsx").unlink()
    report = build_column_report(tmp_path, inbox)
    assert len(report["sources"]) == 1
    assert report["pairs"] == []


def test_spec_entry_uses_entity_name_not_file_path():
    from webapp import _entity_name

    assert _entity_name("Vattenkraft/Vattenkraftverk") == "vattenkraftverk"
    assert _entity_name("Samverkan/Samverkansprocesser") == "samverkansprocesser"


def test_changelog_renders_event_count_and_keeps_watch_status_separate():
    """Statusraden ägs av knappen och får inte skrivas över av tabellrenderingen."""
    assert 'id="watchStatus"' in PAGE
    assert "av ${events.length} händelse(r)" in PAGE


def test_changelog_tab_knows_all_event_types():
    for event in ("source_added", "source_changed", "source_removed",
                  "source_unchanged", "source_unreadable", "source_recovered"):
        assert event in PAGE, event
