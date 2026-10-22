"""Tester för läsning/skrivning av enskilda flikar."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from excel_merge.config import SourceConfig
from excel_merge.io import SourceReadError, read_sheet
from fixtures import CUSTOMERS, ORDERS, build_sample_sources


def test_reads_only_requested_columns(workdir: Path):
    build_sample_sources(workdir)
    source = SourceConfig(
        name="customers",
        path=Path("customers.xlsx"),
        sheet="Customers",
        columns={"customer_id": "customer_id", "name": "customer_name"},
    )
    df = read_sheet(source, workdir)
    assert list(df.columns) == ["customer_id", "customer_name"]
    assert len(df) == len(CUSTOMERS)


def test_applies_dtypes(workdir: Path):
    build_sample_sources(workdir)
    source = SourceConfig(
        name="orders",
        path=Path("orders.xlsx"),
        sheet="Orders",
        columns={"customer_id": "customer_id", "amount": "order_amount"},
        dtypes={"customer_id": "int", "amount": "float"},
    )
    df = read_sheet(source, workdir)
    assert df["customer_id"].dtype.kind == "i"
    assert df["order_amount"].dtype.kind == "f"


def test_missing_sheet_lists_available(workdir: Path):
    build_sample_sources(workdir)
    source = SourceConfig(
        name="customers", path=Path("customers.xlsx"), sheet="Fel", columns={"customer_id": "id"}
    )
    with pytest.raises(SourceReadError, match="Tillgängliga flikar"):
        read_sheet(source, workdir)


def test_missing_column_is_reported(workdir: Path):
    build_sample_sources(workdir)
    source = SourceConfig(
        name="customers",
        path=Path("customers.xlsx"),
        sheet="Customers",
        columns={"customer_id": "id", "finns_inte": "x"},
    )
    with pytest.raises(SourceReadError, match="finns_inte"):
        read_sheet(source, workdir)


def test_missing_file_is_reported(workdir: Path):
    source = SourceConfig(name="x", path=Path("saknas.xlsx"), sheet="S", columns={"a": "a"})
    with pytest.raises(SourceReadError, match="hittades inte"):
        read_sheet(source, workdir)


def test_bad_dtype_is_reported(workdir: Path):
    build_sample_sources(workdir)
    source = SourceConfig(
        name="customers",
        path=Path("customers.xlsx"),
        sheet="Customers",
        columns={"name": "customer_name"},
        dtypes={"name": "int"},
    )
    with pytest.raises(SourceReadError, match="typa"):
        read_sheet(source, workdir)
