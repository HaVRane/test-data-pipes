"""Tester för uppladdningsservern, särskilt skyddet mot felaktiga filnamn."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from upload_server import safe_name  # noqa: E402


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


def test_page_has_valid_css_and_js():
    """Sidan renderas som rå HTML - inga mallklamrar får läcka igenom."""
    from upload_server import PAGE

    assert "{{" not in PAGE and "}}" not in PAGE
    assert "fetch(" in PAGE
    assert "border-radius" in PAGE
