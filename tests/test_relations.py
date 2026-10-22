"""Tester för relationsmodellen och körplanen."""

from __future__ import annotations

import pytest

from excel_merge.relations import (
    RelationSpecError,
    build_plan,
    load_relation_spec,
)

TWO = """\
entities:
  customer: {key: customer_id}
  order: {key: order_id}
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns: {customer_id: customer_id, name: customer_name}
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    columns: {order_id: order_id, customer_id: customer_id}
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
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
    spec = load_relation_spec(_write(tmp_path, TWO))
    assert set(spec.entities) == {"customer", "order"}
    assert spec.entity_sources("order")[0].name == "orders"


def test_plan_starts_with_base_entity(tmp_path):
    spec = load_relation_spec(_write(tmp_path, TWO))
    plan = build_plan(spec, "b")
    assert plan[0].entity == "customer"
    assert plan[1].entity == "order"
    assert plan[1].key == "customer_id"
    assert plan[1].cardinality == "many_to_one"


def test_rejects_source_with_unknown_entity(tmp_path):
    bad = TWO.replace("entity: order", "entity: produkt")
    with pytest.raises(RelationSpecError, match="okänd entitet"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_source_missing_entity_key(tmp_path):
    bad = TWO.replace("columns: {order_id: order_id, customer_id: customer_id}",
                      "columns: {customer_id: customer_id}")
    with pytest.raises(RelationSpecError, match="nyckelkolumn"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_relationship_via_unknown_column(tmp_path):
    bad = TWO.replace("via: customer_id", "via: kund")
    with pytest.raises(RelationSpecError, match="via kolumnen"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_bad_cardinality(tmp_path):
    bad = TWO.replace("cardinality: many_to_one", "cardinality: ibland")
    with pytest.raises(RelationSpecError, match="cardinality"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_bad_orphan_policy(tmp_path):
    bad = TWO.replace("cardinality: many_to_one", "cardinality: many_to_one\n        orphans: ignorera")
    with pytest.raises(RelationSpecError, match="orphans"):
        load_relation_spec(_write(tmp_path, bad))


def test_rejects_unreachable_include(tmp_path):
    """En entitet utan relation till basen får inte inkluderas."""
    disconnected = TWO.replace(
        "      - to: customer\n        via: customer_id\n        cardinality: many_to_one\n", ""
    )
    with pytest.raises(RelationSpecError, match="går inte att nå"):
        load_relation_spec(_write(tmp_path, disconnected))


def test_rejects_build_without_base_source(tmp_path):
    bad = TWO.replace("    base: customer", "    base: order").replace("    include: [order]", "    include: [customer]")
    # nu är order bas men källan 'orders' finns -> ok; testa istället helt okänd bas
    bad = TWO.replace("    base: customer", "    base: saknas")
    with pytest.raises(RelationSpecError, match="okänd bas-entitet"):
        load_relation_spec(_write(tmp_path, bad))


def test_three_source_plan_is_derived_not_hardcoded(tmp_path):
    """Lägg till en tredje entitet: planen ska härledas automatiskt."""
    three = TWO.replace(
        "builds:",
        """  - name: products
    path: p.xlsx
    sheet: S
    entity: product
    columns: {product_id: product_id, customer_id: customer_id}
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
builds:""",
    )
    three = three.replace(
        "  order: {key: order_id}",
        "  order: {key: order_id}\n  product: {key: product_id}",
    )
    three = three.replace("    include: [order]", "    include: [order, product]")
    spec = load_relation_spec(_write(tmp_path, three))
    plan = build_plan(spec, "b")
    assert [s.entity for s in plan] == ["customer", "order", "product"]
