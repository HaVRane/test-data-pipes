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
    build_relationship_map,
    collect_sources,
    safe_name,
)
from fixtures import build_sample_sources, write_workbook


def _isa(tmp_path: Path) -> Path:
    """Datakatalogen som appen läser: data/isa."""
    directory = tmp_path / "data" / "isa"
    directory.mkdir(parents=True)
    return directory


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


def test_collect_sources_lists_name_without_directory_and_extension(tmp_path):
    """Visningsnamnet är filnamnet utan data/isa/ och utan ändelse."""
    build_sample_sources(_isa(tmp_path))
    sources = collect_sources(tmp_path / "data" / "isa")
    names = sorted(s["name"] for s in sources)
    assert names == ["customers", "orders"]
    customers = next(s for s in sources if s["name"] == "customers")
    assert customers["sheets"][0]["name"] == "Customers"
    assert customers["sheets"][0]["rows"] == 4


def test_collect_sources_reports_type_instead_of_extension(tmp_path):
    """Ändelsen ersätts av en Typ-kolumn, så Excel syns som Excel."""
    build_sample_sources(_isa(tmp_path))
    sources = collect_sources(tmp_path / "data" / "isa")
    assert all(s["type"] == "Excel" for s in sources)


def test_collect_sources_keeps_full_relative_path_for_traceability(tmp_path):
    build_sample_sources(_isa(tmp_path))
    sources = collect_sources(tmp_path / "data" / "isa")
    customers = next(s for s in sources if s["name"] == "customers")
    assert customers["file"] == "data/isa/customers.xlsx"


def test_collect_sources_reads_only_the_data_directory(tmp_path):
    """En fil utanför data/isa ska inte dyka upp i listan."""
    isa = _isa(tmp_path)
    build_sample_sources(isa)
    (tmp_path / "data" / "utanfor.xlsx").parent.mkdir(parents=True, exist_ok=True)
    write_workbook(tmp_path / "data" / "utanfor.xlsx", {"U": pd.DataFrame({"a": [1]})})
    sources = collect_sources(isa)
    assert sorted(s["name"] for s in sources) == ["customers", "orders"]


def test_collect_sources_ignores_non_spreadsheets(tmp_path):
    isa = _isa(tmp_path)
    (isa / "anteckning.txt").write_text("nej", encoding="utf-8")
    (isa / "README.md").write_text("nej", encoding="utf-8")
    assert collect_sources(isa) == []


def test_column_report_and_map_agree_on_the_same_column(tmp_path):
    """De två vyerna ska svara likadant om samma kolumn.

    Kolumnrapporten visade ``belopp`` som möjlig nyckel medan källkartan inte
    gjorde det - i samma applikation, på samma data. Båda hämtar nu svaret från
    ``joins.is_key_candidate``, så de kan inte glida isär igen.
    """
    isa = _isa(tmp_path)
    write_workbook(
        isa / "ordrar.xlsx",
        {
            "Ordrar": pd.DataFrame({
                "order_id": [10, 11, 12],
                "belopp": [100, 200, 300],
                "order_date": ["2024-01-01", "2024-02-01", "2024-03-01"],
            })
        },
    )

    report = build_column_report(tmp_path / "data" / "isa")
    source = next(s for s in report["sources"] if s["sheet"] == "Ordrar")
    in_report = {c["name"] for c in source["columns"] if c["candidate_key"]}

    node = next(n for n in build_relationship_map(tmp_path / "data" / "isa")["nodes"])
    in_map = set(node["candidate_keys"])

    assert in_report == in_map, "kolumnrapporten och kartan måste ge samma svar"
    assert "order_id" in in_report
    assert "belopp" not in in_report
    assert "order_date" not in in_report


def test_collect_sources_survives_corrupt_file(tmp_path):
    isa = _isa(tmp_path)
    (isa / "trasig.xlsx").write_bytes(b"detta ar inte ett kalkylark")
    build_sample_sources(isa)
    sources = collect_sources(isa)
    broken = next(s for s in sources if s["name"] == "trasig")
    assert broken["sheets"] == []
    assert "error" in broken


def test_column_report_lists_columns_and_candidates(tmp_path):
    build_sample_sources(_isa(tmp_path))
    report = build_column_report(tmp_path / "data" / "isa")

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
    isa = _isa(tmp_path)
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    write_workbook(isa / "a.xlsx", {"A": pd.DataFrame({"datum": dates, "id": [1, 2, 3]})})
    write_workbook(isa / "b.xlsx", {"B": pd.DataFrame({"datum": dates, "id": [1, 2, 3]})})
    report = build_column_report(isa)
    best = report["pairs"][0]["candidates"][0]
    assert best["left_column"] == "id"


def test_column_report_handles_single_source(tmp_path):
    isa = _isa(tmp_path)
    build_sample_sources(isa)
    (isa / "orders.xlsx").unlink()
    report = build_column_report(isa)
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
