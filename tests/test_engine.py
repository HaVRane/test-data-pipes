"""Tester för körmotorn: att specen faktiskt styr resultatet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from excel_merge.engine import execute_build
from excel_merge.relations import RelationSpecError, build_plan, load_relation_spec
from fixtures import build_sample_sources, write_workbook

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


def _spec_file(workdir: Path, orphans: str = "keep") -> Path:
    path = workdir / "relations.yaml"
    path.write_text(SPEC.replace("__ORPHANS__", orphans), encoding="utf-8")
    return path


@pytest.fixture
def workdir_with_sources(tmp_path: Path) -> Path:
    build_sample_sources(tmp_path)
    return tmp_path


def test_execute_build_writes_output(workdir_with_sources):
    spec = load_relation_spec(_spec_file(workdir_with_sources))
    result = execute_build(spec, "customer_orders")
    assert result.output_path.is_file()
    written = pd.read_excel(result.output_path, sheet_name="Merged")
    assert list(written.columns) == [
        "order_id",
        "customer_id",
        "customer_name",
        "segment",
        "order_amount",
        "order_date",
    ]


def test_orphan_policy_keep_retains_base_rows(workdir_with_sources):
    spec = load_relation_spec(_spec_file(workdir_with_sources, orphans="keep"))
    result = execute_build(spec, "customer_orders")
    assert set(result.frame["customer_id"]) == {1, 2, 3, 4}


def test_orphan_policy_drop_removes_unmatched(workdir_with_sources):
    spec = load_relation_spec(_spec_file(workdir_with_sources, orphans="drop"))
    result = execute_build(spec, "customer_orders")
    assert set(result.frame["customer_id"]) == {1, 2, 4}


def test_orphan_policy_flag_adds_marker(workdir_with_sources):
    spec = load_relation_spec(_spec_file(workdir_with_sources, orphans="flag"))
    result = execute_build(spec, "customer_orders")
    assert "matched_orders" in result.frame.columns
    flagged = result.frame.set_index("customer_id")["matched_orders"]
    assert bool(flagged.loc[1]) is True
    assert bool(flagged.loc[3]) is False


def test_row_counts_reported(workdir_with_sources):
    spec = load_relation_spec(_spec_file(workdir_with_sources))
    result = execute_build(spec, "customer_orders")
    assert result.row_counts == {"customers": 4, "orders": 4}


def test_unknown_build_is_rejected(workdir_with_sources):
    spec = load_relation_spec(_spec_file(workdir_with_sources))
    with pytest.raises(Exception, match="okänt bygge"):
        execute_build(spec, "finns_inte")


def test_three_source_chain_builds_without_code_change(tmp_path):
    """Skalbarhetsbeviset: en tredje källa kopplas in enbart via specen."""
    build_sample_sources(tmp_path)
    write_workbook(
        tmp_path / "segments.xlsx",
        {"Segments": pd.DataFrame({"segment": ["SMB", "Enterprise"], "rabatt": [0.1, 0.25]})},
    )
    spec_text = (
        SPEC.replace("__ORPHANS__", "keep")
        .replace(
            "  order:\n    key: order_id",
            "  order:\n    key: order_id\n  segment:\n    key: segment",
        )
        .replace(
            "builds:",
            """  - name: segment_info
    path: segments.xlsx
    sheet: Segments
    entity: segment
    columns: {segment: segment, rabatt: segment_rabatt}
    relationships:
      - to: customer
        via: segment
        cardinality: many_to_one
        orphans: keep
builds:""",
        )
        .replace("include: [order]", "include: [order, segment]")
        .replace("segment, order_amount", "segment, segment_rabatt, order_amount")
    )
    spec_path = tmp_path / "relations.yaml"
    spec_path.write_text(spec_text, encoding="utf-8")

    spec = load_relation_spec(spec_path)
    plan_entities = [s.entity for s in build_plan(spec, "customer_orders")]
    assert plan_entities == ["customer", "order", "segment"]

    result = execute_build(spec, "customer_orders")
    assert "segment_rabatt" in result.frame.columns
    by_segment = result.frame.groupby("segment")["segment_rabatt"].first()
    assert by_segment["SMB"] == 0.1
    assert by_segment["Enterprise"] == 0.25


def test_disconnected_entity_is_rejected(tmp_path):
    """En entitet som inte hänger ihop med basen ska avvisas, inte tyst ignoreras."""
    build_sample_sources(tmp_path)
    write_workbook(
        tmp_path / "islands.xlsx",
        {"Islands": pd.DataFrame({"island_id": [1, 2], "namn": ["A", "B"]})},
    )
    spec_text = SPEC.replace("__ORPHANS__", "keep").replace(
        "  order:\n    key: order_id",
        "  order:\n    key: order_id\n  island:\n    key: island_id",
    ).replace(
        "builds:",
        """  - name: islands
    path: islands.xlsx
    sheet: Islands
    entity: island
    columns: {island_id: island_id, namn: island_namn}
builds:""",
    ).replace("include: [order]", "include: [order, island]")
    spec_path = tmp_path / "relations.yaml"
    spec_path.write_text(spec_text, encoding="utf-8")
    with pytest.raises(RelationSpecError, match="går inte att nå"):
        load_relation_spec(spec_path)
