"""Ämnesområdena i webbapplikationen: endpointen och fliken.

Testerna bevakar att vyn är kopplad hela vägen - fliken finns, laddaren körs,
endpointen svarar - och att ett fel i specen blir ett begripligt meddelande i
stället för en tom sida eller en krasch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from webapp import PAGE, build_subject_report  # noqa: E402

SPEC = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
      segment: segment
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    dtypes:
      amount: float
    columns:
      order_id: order_id
      customer_id: customer_id
      amount: order_amount
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out.xlsx
    sheet: Out
"""


@pytest.fixture()
def spec_dir(tmp_path: Path) -> Path:
    pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"], "segment": ["X", "Y"]}).to_excel(
        tmp_path / "c.xlsx", index=False, sheet_name="S"
    )
    pd.DataFrame({"order_id": [1, 2], "customer_id": [1, 2], "amount": [10.0, 20.0]}).to_excel(
        tmp_path / "o.xlsx", index=False, sheet_name="S"
    )
    (tmp_path / "relations.yaml").write_text(SPEC, encoding="utf-8")
    return tmp_path


def test_page_has_a_subjects_tab():
    assert "Ämnesområden" in PAGE
    assert 'data-tab="subjects"' in PAGE
    assert 'id="subjects"' in PAGE
    assert "loadSubjects" in PAGE
    assert 'id="subjectsBody"' in PAGE


def test_tab_is_wired_to_its_loader():
    """Fliken måste faktiskt anropa laddaren, annars visas inget."""
    assert 'btn.dataset.tab === "subjects"' in PAGE


def test_page_still_has_six_tabs():
    for tab in (
        "Anslut datakälla",
        "Indata",
        "Kolumner och koppling",
        "Indatarelationer",
        "Ämnesområden",
        "Ändringslogg",
    ):
        assert tab in PAGE


def test_report_derives_facts_and_dimensions(spec_dir):
    report = build_subject_report(spec_dir / "relations.yaml")
    assert report.get("error") is None
    assert [s["name"] for s in report["subjects"]] == ["customer_orders"]
    subject = report["subjects"][0]
    assert [f["entity"] for f in subject["facts"]] == ["order"]
    assert [d["entity"] for d in subject["dimensions"]] == ["customer"]


def test_report_measures_include_kind_and_reason(spec_dir):
    report = build_subject_report(spec_dir / "relations.yaml")
    measure = report["subjects"][0]["facts"][0]["measures"][0]
    assert measure["column"] == "order_amount"
    assert measure["kind"] == "numeric"
    assert measure["reason"]


def test_report_includes_spec_path(spec_dir):
    report = build_subject_report(spec_dir / "relations.yaml")
    assert report["spec"].endswith("relations.yaml")


def test_report_has_all_sections(spec_dir):
    report = build_subject_report(spec_dir / "relations.yaml")
    assert set(report) >= {"subjects", "conformed", "unassigned", "spec", "missing_sources"}


def test_missing_spec_file_gives_a_message_not_a_crash(tmp_path):
    report = build_subject_report(tmp_path / "finns-inte.yaml")
    assert report["subjects"] == []
    assert "hittades inte" in report["error"]


def test_broken_spec_gives_a_message_not_a_crash(tmp_path):
    """En ogiltig spec ska bli ett begripligt fel i vyn."""
    (tmp_path / "broken.yaml").write_text("version: 1\nsources: []\n", encoding="utf-8")
    report = build_subject_report(tmp_path / "broken.yaml")
    assert report["subjects"] == []
    assert report["error"], "felet ska följa med i svaret"


def test_missing_source_is_reported_but_does_not_break_the_view(spec_dir):
    """En källa vars fil saknas tas bort, och vyn ska peka ut vilken.

    Att bara säga "ingen källa tillhandahåller order" är svårt att åtgärda.
    Felet ska namnge filen som försvunnit.
    """
    (spec_dir / "o.xlsx").unlink()
    report = build_subject_report(spec_dir / "relations.yaml")
    assert report["subjects"] == []
    assert report["missing_sources"] == ["orders"]
    assert "orders" in report["error"]


def test_a_spec_without_builds_still_renders(spec_dir):
    """Saknas byggen ska vyn härleda områden ur grafen i stället för att ge upp."""
    path = spec_dir / "relations.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.split("builds:")[0], encoding="utf-8")
    report = build_subject_report(path)
    assert report.get("error") is None
    assert report["subjects"], "utan byggen ska grafen ge ett område"


def test_report_is_deterministic(spec_dir):
    first = build_subject_report(spec_dir / "relations.yaml")
    second = build_subject_report(spec_dir / "relations.yaml")
    assert first == second


def test_report_writes_nothing_to_the_spec(spec_dir):
    """Vyn får inte röra specen - den är härledd, inte redigerad."""
    path = spec_dir / "relations.yaml"
    before = path.read_text(encoding="utf-8")
    build_subject_report(path)
    assert path.read_text(encoding="utf-8") == before
