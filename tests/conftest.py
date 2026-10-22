"""Delade pytest-fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures import build_sample_sources  # noqa: E402

CONFIG_TEMPLATE = """\
version: 1
sources:
  - name: customers
    path: {customers}
    sheet: Customers
    dtypes:
      customer_id: int
    columns:
      customer_id: customer_id
      name: customer_name
      segment: segment
  - name: orders
    path: {orders}
    sheet: Orders
    dtypes:
      customer_id: int
      amount: float
    columns:
      customer_id: customer_id
      amount: order_amount
      order_date: order_date
join:
  on: [customer_id]
  how: {how}
  validate: {validate}
output:
  path: {output}
  sheet: Merged
  columns: [customer_id, customer_name, segment, order_amount, order_date]
"""


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Katalog med två ifyllda Excel-filer och en tillhörande konfiguration."""
    build_sample_sources(tmp_path)
    return tmp_path


@pytest.fixture
def make_config(workdir: Path):
    """Skriv en konfigurationsfil i workdir och returnera dess sökväg."""

    def _make(how: str = "left", validate: str = "many_to_one") -> Path:
        config_path = workdir / "pipeline.yaml"
        config_path.write_text(
            CONFIG_TEMPLATE.format(
                customers=(workdir / "customers.xlsx").as_posix(),
                orders=(workdir / "orders.xlsx").as_posix(),
                output=(workdir / "out" / "merged.xlsx").as_posix(),
                how=how,
                validate=validate,
            ),
            encoding="utf-8",
        )
        return config_path

    return _make
