"""Tester för profilering och nyckelförslag."""

from __future__ import annotations

import pandas as pd
import pytest

from excel_merge.profile import (
    column_stats,
    compare_keys,
    discover_candidate_keys,
    profile_pair,
    suggest_spec_entry,
)


def test_column_stats_flags_unique_key():
    stats = column_stats(pd.Series([1, 2, 3], name="id"))
    assert stats.is_candidate_key
    assert stats.distinct == 3


def test_column_stats_rejects_duplicates_and_nulls():
    assert not column_stats(pd.Series([1, 1, 2], name="id")).is_candidate_key
    assert not column_stats(pd.Series([1, None, 2], name="id")).is_candidate_key


def test_compare_keys_reports_many_to_one():
    left = pd.Series([1, 2, 2, 3], name="customer_id")
    right = pd.Series([1, 2, 3], name="customer_id")
    comparison = compare_keys(left, right)
    assert comparison.cardinality == "many_to_one"
    assert comparison.matched == 3
    assert comparison.orphans_left == 0


def test_compare_keys_counts_orphans():
    left = pd.Series([1, 2, 9], name="customer_id")
    right = pd.Series([1, 2, 3], name="customer_id")
    comparison = compare_keys(left, right)
    assert comparison.orphans_left == 1
    assert comparison.orphans_right == 1
    assert comparison.coverage_left == pytest.approx(2 / 3)


def test_compare_keys_detects_type_mismatch():
    left = pd.Series([1, 2], name="id")
    right = pd.Series(["1", "2"], name="id")
    comparison = compare_keys(left, right)
    assert comparison.type_mismatch
    assert not comparison.is_plausible_join


def test_compare_keys_treats_numeric_and_text_as_different():
    left = pd.Series([10, 20], name="k")
    right = pd.Series([10.0, 20.0], name="k")
    # båda är numeriska -> ingen typkrock, och värdena ska matcha
    comparison = compare_keys(left, right)
    assert not comparison.type_mismatch
    assert comparison.matched == 2


def test_discover_candidate_keys_ranks_by_coverage():
    left = pd.DataFrame({"customer_id": [1, 2, 3], "other": [9, 8, 7]})
    right = pd.DataFrame({"customer_id": [1, 2, 3], "other": [1, 1, 1]})
    candidates = discover_candidate_keys(left, right)
    assert candidates[0].left == "customer_id"


def test_discover_candidate_keys_skips_unrelated_columns():
    left = pd.DataFrame({"a": [1, 2, 3]})
    right = pd.DataFrame({"a": [100, 200, 300]})
    assert discover_candidate_keys(left, right) == []


def test_suggest_spec_entry_marks_decisions_as_unconfirmed():
    comparison = compare_keys(pd.Series([1, 2], name="id"), pd.Series([1, 2], name="id"))
    entry = suggest_spec_entry(comparison, "customers")
    assert "to: customers" in entry
    assert "cardinality: one_to_one" in entry
    assert "bekräfta" in entry


def test_profile_pair_validates_key_names():
    left = pd.DataFrame({"a": [1]})
    right = pd.DataFrame({"a": [1]})
    with pytest.raises(KeyError, match="finns inte"):
        profile_pair(left, right, "saknas", "a")
