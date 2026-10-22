"""Tester för innehållsfingeravtryck."""

from __future__ import annotations

import pandas as pd
import pytest

from excel_merge.fingerprint import canonical_cell, fingerprint_frame


def test_same_content_gives_same_fingerprint():
    a = pd.DataFrame({"id": [1, 2], "namn": ["A", "B"]})
    b = pd.DataFrame({"id": [1, 2], "namn": ["A", "B"]})
    assert fingerprint_frame(a).digest == fingerprint_frame(b).digest


def test_changed_value_changes_fingerprint():
    a = pd.DataFrame({"id": [1, 2]})
    b = pd.DataFrame({"id": [1, 3]})
    assert fingerprint_frame(a).digest != fingerprint_frame(b).digest


def test_int_and_float_one_are_the_same():
    """Excel ger samma tal olika Python-typ mellan läsningar."""
    assert canonical_cell(1) == canonical_cell(1.0)
    assert canonical_cell(42) == canonical_cell(42.0)


def test_numeric_text_and_number_are_the_same():
    assert canonical_cell("42") == canonical_cell(42)


def test_none_and_nan_are_the_same():
    assert canonical_cell(None) == canonical_cell(float("nan"))
    assert canonical_cell(None) == canonical_cell(pd.NA)


def test_date_and_midnight_timestamp_are_the_same():
    assert canonical_cell(pd.Timestamp("2024-01-05")) == canonical_cell(
        pd.Timestamp("2024-01-05 00:00:00")
    )


def test_timestamp_with_time_keeps_time():
    assert "T13:45" in canonical_cell(pd.Timestamp("2024-01-05 13:45"))


def test_row_order_matters():
    a = pd.DataFrame({"id": [1, 2]})
    b = pd.DataFrame({"id": [2, 1]})
    assert fingerprint_frame(a).digest != fingerprint_frame(b).digest


def test_column_order_matters():
    a = pd.DataFrame({"id": [1], "namn": ["A"]})
    b = pd.DataFrame({"id": [1], "namn": ["A"]})[["namn", "id"]]
    assert fingerprint_frame(a).digest != fingerprint_frame(b).digest


def test_column_name_change_changes_fingerprint():
    a = pd.DataFrame({"id": [1]})
    b = pd.DataFrame({"ID": [1]})
    assert fingerprint_frame(a).digest != fingerprint_frame(b).digest


def test_fingerprint_records_rows_and_columns():
    frame = pd.DataFrame({"id": [1, 2, 3], "namn": ["A", "B", "C"]})
    fp = fingerprint_frame(frame)
    assert fp.rows == 3
    assert fp.columns == ["id", "namn"]


def test_whitespace_in_text_is_ignored():
    assert canonical_cell("  Acme  ") == canonical_cell("Acme")


def test_fingerprint_is_stable_across_reads(tmp_path):
    """Kärnkravet: om Excel skriver om filen utan att datan ändras ska inget larm ske."""
    path = tmp_path / "a.xlsx"
    frame = pd.DataFrame({"id": [1, 2], "belopp": [10.0, 20.5]})
    frame.to_excel(path, index=False, engine="openpyxl")
    first = fingerprint_frame(pd.read_excel(path, engine="openpyxl"))

    # Läs och skriv om filen, som Excel gör när någon öppnar och sparar.
    again = pd.read_excel(path, engine="openpyxl")
    again.to_excel(path, index=False, engine="openpyxl")
    second = fingerprint_frame(pd.read_excel(path, engine="openpyxl"))

    assert first.digest == second.digest
