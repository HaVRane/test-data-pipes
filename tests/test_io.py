"""Tester för läsning av enskilda flikar."""

from __future__ import annotations

from pathlib import Path

import pytest

from excel_merge.io import SourceReadError, read_sheet
from excel_merge.relations import SourceSpec
from fixtures import CUSTOMERS, build_sample_sources


def _source(name="customers", sheet="Customers", **kwargs) -> SourceSpec:
    defaults = dict(
        name=name,
        path=Path("customers.xlsx"),
        sheet=sheet,
        entity="customer",
        columns={"customer_id": "customer_id", "name": "customer_name"},
    )
    defaults.update(kwargs)
    return SourceSpec(**defaults)


def test_reads_only_requested_columns(workdir: Path):
    build_sample_sources(workdir)
    df = read_sheet(_source(), workdir)
    assert list(df.columns) == ["customer_id", "customer_name"]
    assert len(df) == len(CUSTOMERS)


def test_applies_dtypes(workdir: Path):
    build_sample_sources(workdir)
    source = _source(
        name="orders",
        path=Path("orders.xlsx"),
        sheet="Orders",
        entity="order",
        columns={"customer_id": "customer_id", "amount": "order_amount"},
        dtypes={"customer_id": "int", "amount": "float"},
    )
    df = read_sheet(source, workdir)
    assert df["customer_id"].dtype.kind == "i"
    assert df["order_amount"].dtype.kind == "f"


def test_missing_sheet_lists_available(workdir: Path):
    build_sample_sources(workdir)
    with pytest.raises(SourceReadError, match="Tillgängliga flikar"):
        read_sheet(_source(sheet="Fel"), workdir)


def test_missing_column_is_reported(workdir: Path):
    build_sample_sources(workdir)
    source = _source(columns={"customer_id": "id", "finns_inte": "x"})
    with pytest.raises(SourceReadError, match="finns_inte"):
        read_sheet(source, workdir)


def test_missing_file_is_reported(workdir: Path):
    with pytest.raises(SourceReadError, match="hittades inte"):
        read_sheet(_source(path=Path("saknas.xlsx")), workdir)


def test_bad_dtype_is_reported(workdir: Path):
    build_sample_sources(workdir)
    source = _source(columns={"name": "customer_name"}, dtypes={"name": "int"})
    with pytest.raises(SourceReadError, match="typa"):
        read_sheet(source, workdir)
