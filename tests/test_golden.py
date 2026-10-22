"""Golden-file-test: låser hela utdata för standardbygget.

Ändrar man specen medvetet uppdaterar man filen med:
    UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py
Diffen blir då synlig i git, vilket är precis vad en granskande agent behöver se.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from excel_merge.engine import execute_build
from excel_merge.relations import load_relation_spec
from fixtures import build_sample_sources

GOLDEN = Path(__file__).parent / "golden" / "customer_orders.csv"

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
        orphans: keep
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out/merged.xlsx
    sheet: Merged
    columns: [order_id, customer_id, customer_name, segment, order_amount, order_date]
"""


def _canonical(frame: pd.DataFrame) -> pd.DataFrame:
    """Gör utdata jämförbar mellan pandas-objekt och CSV (t.ex. datum)."""
    frame = frame.reset_index(drop=True).copy()
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = frame[column].dt.strftime("%Y-%m-%d")
    return frame


@pytest.fixture
def spec_path(tmp_path):
    build_sample_sources(tmp_path)
    path = tmp_path / "relations.yaml"
    path.write_text(SPEC, encoding="utf-8")
    return path


def test_output_matches_golden(spec_path):
    result = _canonical(execute_build(load_relation_spec(spec_path), "customer_orders").frame)

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(GOLDEN, index=False)
        return

    assert GOLDEN.is_file(), (
        f"Saknar golden-fil {GOLDEN}. Skapa den med UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py"
    )
    expected = pd.read_csv(GOLDEN).astype(object).where(lambda d: d.notna(), None)
    actual = result.astype(object).where(lambda d: d.notna(), None)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
