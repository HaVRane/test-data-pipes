"""Tester för inventeringsverktyget."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from inspect_uploads import describe_workbook, find_workbooks, report, suggest_source_entry  # noqa: E402
from fixtures import build_sample_sources, write_workbook


def test_finds_only_spreadsheets(tmp_path):
    build_sample_sources(tmp_path)
    (tmp_path / "anteckning.txt").write_text("inte ett ark", encoding="utf-8")
    found = [p.name for p in find_workbooks(tmp_path)]
    assert found == ["customers.xlsx", "orders.xlsx"]


def test_finds_spreadsheets_in_subdirectories(tmp_path):
    nested = tmp_path / "inbox" / "vecka1"
    nested.mkdir(parents=True)
    build_sample_sources(nested)
    assert len(find_workbooks(tmp_path)) == 2


def test_missing_directory_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="finns inte"):
        find_workbooks(tmp_path / "saknas")


def test_describe_reads_all_sheets(tmp_path):
    write_workbook(
        tmp_path / "bok.xlsx",
        {"Forsta": pd.DataFrame({"a": [1]}), "Andra": pd.DataFrame({"b": [2]})},
    )
    sheets = describe_workbook(tmp_path / "bok.xlsx")
    assert [name for name, _ in sheets] == ["Forsta", "Andra"]


def test_suggest_source_entry_uses_sheet_name_as_slug(tmp_path):
    frame = pd.DataFrame({"Customer ID": [1], "Namn": ["A"]})
    entry = suggest_source_entry(tmp_path / "Min Fil.xlsx", "Kund Data", frame)
    assert "name: kund_data" in entry
    assert "sheet: Kund Data" in entry
    # originalkolumnen behålls som nyckel, målet blir en slug
    assert "Customer ID: customer_id" in entry
    assert "Namn: namn" in entry


def test_report_returns_zero_and_lists_sheets(tmp_path, capsys):
    build_sample_sources(tmp_path)
    assert report(tmp_path) == 0
    out = capsys.readouterr().out
    assert "flik 'Customers'" in out
    assert "möjlig nyckel" in out


def test_report_without_workbooks_returns_one(tmp_path, capsys):
    assert report(tmp_path) == 1
    assert "Inga arbetsböcker" in capsys.readouterr().out


def test_report_compares_against_reference(tmp_path, capsys):
    build_sample_sources(tmp_path)
    report(tmp_path, reference=tmp_path / "customers.xlsx")
    out = capsys.readouterr().out
    assert "kandidatkoppling mot referensen" in out
