"""Tester för relationsspecens validering."""

from __future__ import annotations

import pytest

from excel_merge.relations import RelationSpecError, load_relation_spec

VALID = """\
entities:
  customer: {key: customer_id}
  order: {key: order_id}
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns: {customer_id: customer_id}
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    columns: {order_id: order_id, customer_id: customer_id}
    relationships:
      - to: customer
        via: customer_id
builds:
  - name: b
    base: customer
    include: [order]
    output: out.xlsx
    sheet: Out
"""


def _write(tmp_path, text):
    path = tmp_path / "r.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_spec(tmp_path):
    spec = load_relation_spec(_write(tmp_path, VALID))
    assert [s.name for s in spec.sources] == ["customers", "orders"]
    assert spec.version == 1
    assert spec.builds[0].name == "b"


def test_rejects_missing_file(tmp_path):
    with pytest.raises(RelationSpecError, match="hittades inte"):
        load_relation_spec(tmp_path / "nope.yaml")


def test_rejects_duplicate_source_names(tmp_path):
    dup = VALID.replace("name: orders", "name: customers")
    with pytest.raises(RelationSpecError, match="unika"):
        load_relation_spec(_write(tmp_path, dup))


def test_rejects_source_without_columns(tmp_path):
    bad = VALID.replace("    columns: {customer_id: customer_id}\n", "")
    with pytest.raises(RelationSpecError, match="columns"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_build_with_empty_include(tmp_path):
    bad = VALID.replace("    include: [order]", "    include: []")
    with pytest.raises(RelationSpecError, match="include"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_missing_entity_section(tmp_path):
    bad = VALID.replace("entities:\n  customer: {key: customer_id}\n  order: {key: order_id}\n", "")
    with pytest.raises(RelationSpecError, match="entities"):
        load_relation_spec(_write(tmp_path, bad))


def test_defaults_are_applied(tmp_path):
    spec = load_relation_spec(_write(tmp_path, VALID))
    rel = spec.sources[1].relationships[0]
    assert rel.cardinality == "many_to_one"
    assert rel.orphans == "keep"
