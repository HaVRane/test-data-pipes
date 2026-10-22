"""Tester för sammanslagningen - kärnan i dataflödet."""

from __future__ import annotations

import pandas as pd
import pytest

from excel_merge.config import load_config
from excel_merge.pipeline import PipelineError, merge_sources, run_pipeline
from fixtures import CUSTOMERS, ORDERS


def test_left_join_keeps_all_customers(make_config):
    config = load_config(make_config(how="left"))
    result = merge_sources(config)
    # 3 kunder har ordrar, kund 3 har ingen -> vänsterkoppling ger 4 rader (3 + 1 utan order)
    assert len(result) == 4
    assert set(result["customer_id"]) == {1, 2, 3, 4}


def test_left_join_leaves_nan_for_missing_order(make_config):
    config = load_config(make_config(how="left"))
    result = merge_sources(config).set_index("customer_id")
    assert pd.isna(result.loc[3, "order_amount"])


def test_columns_are_renamed_per_config(make_config):
    config = load_config(make_config())
    result = merge_sources(config)
    assert "customer_name" in result.columns
    assert "order_amount" in result.columns
    assert "name" not in result.columns


def test_inner_join_drops_customer_without_order(make_config):
    config = load_config(make_config(how="inner"))
    result = merge_sources(config)
    assert set(result["customer_id"]) == {1, 2, 4}


def test_validate_catches_one_to_many(make_config, workdir):
    """Två ordrar för samma kund ska fångas av validate=many_to_one."""
    from fixtures import write_workbook

    dup = pd.concat([ORDERS, ORDERS.iloc[[0]]], ignore_index=True)
    write_workbook(workdir / "orders.xlsx", {"Orders": dup})
    config = load_config(make_config(validate="many_to_one"))
    with pytest.raises(PipelineError, match="sammanslagningen misslyckades"):
        merge_sources(config)


def test_validate_off_allows_duplicates(make_config, workdir):
    from fixtures import write_workbook

    dup = pd.concat([ORDERS, ORDERS.iloc[[0]]], ignore_index=True)
    write_workbook(workdir / "orders.xlsx", {"Orders": dup})
    config = load_config(make_config(validate="none"))
    assert len(merge_sources(config)) == 5


def test_output_columns_and_order(make_config):
    config = load_config(make_config())
    result = merge_sources(config)
    projected = result[config.output.columns]
    assert list(projected.columns) == [
        "customer_id",
        "customer_name",
        "segment",
        "order_amount",
        "order_date",
    ]


def test_run_pipeline_writes_excel(make_config):
    config = load_config(make_config())
    result = run_pipeline(config)
    assert result.output_path.is_file()
    written = pd.read_excel(result.output_path, sheet_name="Merged")
    assert list(written.columns) == config.output.columns
    assert len(written) == len(result.frame)
    assert result.row_counts == {"customers": len(CUSTOMERS), "orders": len(ORDERS)}


def test_run_pipeline_is_deterministic(make_config):
    config = load_config(make_config())
    first = run_pipeline(config).frame
    second = run_pipeline(config).frame
    pd.testing.assert_frame_equal(first, second)
