"""En saknad källa ska behandlas som en borttagen källa.

Regeln: om filen eller fliken inte finns så finns källan inte. Den ska då bort
ur modellen - precis som om posten struktis ur specen. En trasig fil är något
annat: den finns kvar, vi kan bara inte tolka den.
"""

from __future__ import annotations


import pandas as pd
import pytest

from excel_merge.io import (
    SourceMissingError,
    read_sheet,
    source_is_present,
)
from excel_merge.relations import load_relation_spec, resolve_present_spec

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
    columns: {customer_id: customer_id, name: customer_name}
  - name: orders
    path: orders.xlsx
    sheet: Orders
    entity: order
    dtypes: {customer_id: int}
    columns: {order_id: order_id, customer_id: customer_id}
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out/merged.xlsx
    sheet: Merged
    columns: [order_id, customer_id, name]
"""


@pytest.fixture()
def workdir(tmp_path):
    (tmp_path / "customers.xlsx").parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]}).to_excel(
        tmp_path / "customers.xlsx", index=False, sheet_name="Customers"
    )
    pd.DataFrame({"order_id": [10, 11], "customer_id": [1, 2]}).to_excel(
        tmp_path / "orders.xlsx", index=False, sheet_name="Orders"
    )
    (tmp_path / "relations.yaml").write_text(SPEC, encoding="utf-8")
    return tmp_path


def _spec(workdir):
    return load_relation_spec(workdir / "relations.yaml")


def test_missing_file_raises_the_specific_error(workdir):
    spec = _spec(workdir)
    (workdir / "orders.xlsx").unlink()
    source = next(s for s in spec.sources if s.name == "orders")
    with pytest.raises(SourceMissingError):
        read_sheet(source, workdir)


def test_missing_sheet_raises_the_specific_error(workdir):
    """En flik som inte finns är samma slags frånvaro som en saknad fil."""
    spec = _spec(workdir)
    bad = next(s for s in spec.sources if s.name == "orders")
    from dataclasses import replace

    with pytest.raises(SourceMissingError):
        read_sheet(replace(bad, sheet="FinnsInte"), workdir)


def test_broken_file_is_not_a_missing_source(workdir):
    """En trasig fil är ett läsproblem, inte en frånvaro."""
    spec = _spec(workdir)
    (workdir / "orders.xlsx").write_bytes(b"inte ett kalkylark")
    source = next(s for s in spec.sources if s.name == "orders")
    assert source_is_present(source, workdir) is True
    with pytest.raises(Exception) as exc:
        read_sheet(source, workdir)
    assert not isinstance(exc.value, SourceMissingError)


def test_source_is_present_follows_the_sheet(workdir):
    spec = _spec(workdir)
    source = next(s for s in spec.sources if s.name == "orders")
    assert source_is_present(source, workdir) is True
    from dataclasses import replace

    assert source_is_present(replace(source, sheet="FinnsInte"), workdir) is False


def test_reduced_spec_drops_the_missing_source(workdir):
    spec = _spec(workdir)
    (workdir / "orders.xlsx").unlink()
    reduced = spec.without_missing_sources()
    assert [s.name for s in reduced.sources] == ["customers"]


def test_reduced_spec_keeps_present_sources(workdir):
    spec = _spec(workdir)
    reduced = spec.without_missing_sources()
    assert [s.name for s in reduced.sources] == ["customers", "orders"]


def test_missing_base_source_fails_like_a_struck_spec_entry(workdir):
    """Saknas bas-källan blir felet detsamma som om posten aldrig funnits."""
    from excel_merge.relations import RelationSpecError

    spec = _spec(workdir)
    (workdir / "customers.xlsx").unlink()
    with pytest.raises(RelationSpecError, match="ingen källa tillhandahåller"):
        resolve_present_spec(spec)


def test_missing_source_is_not_part_of_the_model(workdir):
    """Källan ska bort, inte bara markeras - den finns inte i den reducerade specen."""
    spec = _spec(workdir)
    (workdir / "orders.xlsx").unlink()
    assert spec.missing_source_names() == ["orders"]
    reduced = spec.without_missing_sources()
    assert reduced.entity_sources("order") == []
    assert reduced.missing_source_names() == []


def test_a_missing_source_is_listed_by_name(workdir):
    spec = _spec(workdir)
    (workdir / "customers.xlsx").unlink()
    assert spec.missing_source_names() == ["customers"]
