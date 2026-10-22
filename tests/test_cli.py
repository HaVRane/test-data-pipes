"""End-to-end-test av kommandoradsgränssnittet, inklusive felvägar."""

from __future__ import annotations

import pandas as pd
import pytest

from excel_merge.cli import main
from fixtures import build_sample_sources

SPEC = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
sources:
  - name: customers
    path: customers.xlsx
    sheet: Customers
    entity: customer
    dtypes: {customer_id: int}
    columns: {customer_id: customer_id, name: customer_name, segment: segment}
  - name: orders
    path: orders.xlsx
    sheet: Orders
    entity: order
    dtypes: {customer_id: int, amount: float}
    columns: {order_id: order_id, customer_id: customer_id, amount: order_amount, order_date: order_date}
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
        orphans: __ORPHANS__
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out/merged.xlsx
    sheet: Merged
    columns: [order_id, customer_id, customer_name, segment, order_amount, order_date]
"""


@pytest.fixture
def spec_file(tmp_path):
    build_sample_sources(tmp_path)

    def _make(orphans: str = "keep"):
        path = tmp_path / "relations.yaml"
        path.write_text(SPEC.replace("__ORPHANS__", orphans), encoding="utf-8")
        return path

    return _make


def test_cli_run_success(spec_file, capsys):
    assert main(["run", "--spec", str(spec_file())]) == 0
    out = capsys.readouterr().out
    assert "läste customers: 4 rader" in out
    assert "skrev" in out


def test_cli_run_specific_build(spec_file, capsys):
    assert main(["run", "--spec", str(spec_file()), "--build", "customer_orders"]) == 0
    assert "customer_orders" in capsys.readouterr().out


def test_cli_returns_1_on_broken_spec(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sources: []\n", encoding="utf-8")
    assert main(["run", "--spec", str(bad)]) == 1
    assert "FEL" in capsys.readouterr().err


def test_cli_reports_missing_source_file(tmp_path, spec_file, capsys):
    spec = spec_file()
    (tmp_path / "customers.xlsx").unlink()
    assert main(["run", "--spec", str(spec)]) == 1
    assert "hittades inte" in capsys.readouterr().err


@pytest.mark.parametrize("orphans,expected_rows", [("keep", 4), ("drop", 3)])
def test_cli_orphan_policies(spec_file, orphans, expected_rows):
    spec = spec_file(orphans=orphans)
    assert main(["run", "--spec", str(spec)]) == 0
    written = pd.read_excel(spec.parent / "out" / "merged.xlsx", sheet_name="Merged")
    assert len(written) == expected_rows


def test_cli_plan_prints_derived_order(spec_file, capsys):
    assert main(["plan", "--spec", str(spec_file())]) == 0
    out = capsys.readouterr().out
    assert "bygge 'customer_orders'" in out
    assert "1. customers" in out
    assert "2. orders" in out


def test_cli_profile_prints_key_evidence(spec_file, capsys):
    assert main(["profile", "--spec", str(spec_file())]) == 0
    out = capsys.readouterr().out
    assert "Kolumnprofil per källa" in out
    assert "customer_id" in out
    assert "bekräfta" in out
    # förslaget ska tala entitetsspråk, inte källnamn, så det kan klistras in i specen
    assert "to: order" in out


def test_cli_requires_spec_argument():
    with pytest.raises(SystemExit):
        main(["profile"])
