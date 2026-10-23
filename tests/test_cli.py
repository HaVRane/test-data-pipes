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
    """En saknad källa tas bort ur modellen, som om posten struktis ur specen.

    Bygget behöver customers som bas. När källan försvinner blir felet därför
    exakt detsamma som om posten aldrig funnits i specen.
    """
    spec = spec_file()
    (tmp_path / "customers.xlsx").unlink()
    assert main(["run", "--spec", str(spec)]) == 1
    captured = capsys.readouterr()
    assert "customers" in captured.err
    assert "tas bort ur modellen" in captured.err
    assert "ingen källa tillhandahåller" in captured.err


def test_cli_run_succeeds_when_an_unused_source_is_missing(tmp_path, spec_file, capsys):
    """Saknas en källa som bygget inte använder ska körningen ändå lyckas.

    Källan ska ändå nämnas, så att en felstavad sökväg inte försvinner tyst.
    """
    spec = spec_file()
    regions = tmp_path / "regions.xlsx"
    pd.DataFrame({"region_id": ["N", "S"]}).to_excel(regions, index=False, sheet_name="Regions")
    text = spec.read_text(encoding="utf-8").replace(
        "builds:",
        "  - name: regions\n"
        "    path: regions.xlsx\n"
        "    sheet: Regions\n"
        "    entity: region\n"
        "    columns: {region_id: region_id}\n"
        "builds:",
    ).replace("entities:", "entities:\n  region:\n    key: region_id")
    spec.write_text(text, encoding="utf-8")

    regions.unlink()
    assert main(["run", "--spec", str(spec)]) == 0
    captured = capsys.readouterr()
    assert "regions" in captured.err
    assert "tas bort ur modellen" in captured.err
    written = pd.read_excel(spec.parent / "out" / "merged.xlsx", sheet_name="Merged")
    assert len(written) == 4


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


def test_cli_subjects_prints_facts_dimensions_and_measures(spec_file, capsys):
    """Kommandot ska visa härledningen, med skäl, utan att röra specen."""
    path = spec_file()
    before = path.read_text(encoding="utf-8")

    assert main(["subjects", "--spec", str(path)]) == 0
    out = capsys.readouterr().out

    assert "ämnesområde: customer_orders" in out
    assert "fakta: order" in out
    assert "dimension: customer" in out
    assert "mått: order_amount [numeric]" in out
    assert "mått: order_date [datetime]" in out
    # Nycklar och främmande nycklar får inte dyka upp som mått.
    assert "mått: order_id" not in out
    assert "mått: customer_id" not in out
    assert "främmande nyckel: customer_id -> customer" in out
    # Härledningen är en vy. Specen ska vara orörd.
    assert path.read_text(encoding="utf-8") == before


def test_cli_subjects_reports_unassigned_entities(tmp_path, capsys):
    """En entitet med källa men utanför alla byggen ska rapporteras."""
    pd.DataFrame({"customer_id": [1], "name": ["A"]}).to_excel(
        tmp_path / "c.xlsx", index=False, sheet_name="S"
    )
    pd.DataFrame({"lonely_id": [1], "value": [5.0]}).to_excel(
        tmp_path / "l.xlsx", index=False, sheet_name="S"
    )
    spec = tmp_path / "relations.yaml"
    spec.write_text(
        """\
version: 1
entities:
  customer: {key: customer_id}
  lonely: {key: lonely_id}
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns: {customer_id: customer_id, name: customer_name}
  - name: lonely
    path: l.xlsx
    sheet: S
    entity: lonely
    dtypes: {value: float}
    columns: {lonely_id: lonely_id, value: lonely_value}
builds:
  - name: customer_subject
    base: customer
    include: [customer]
    output: out.xlsx
    sheet: S
""",
        encoding="utf-8",
    )
    assert main(["subjects", "--spec", str(spec)]) == 0
    out = capsys.readouterr().out
    assert "utanför varje ämnesområde" in out
    assert "lonely" in out


def test_cli_requires_spec_argument():
    with pytest.raises(SystemExit):
        main(["profile"])
