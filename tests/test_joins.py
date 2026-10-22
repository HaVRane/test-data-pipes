"""Tester för rangordning av kopplingskandidater."""

from __future__ import annotations

import pandas as pd

from excel_merge.joins import best_join, rank_join_candidates, score_candidate
from excel_merge.profile import compare_keys


def test_unique_id_column_is_recommended():
    left = pd.DataFrame({"kund_id": [1, 2, 3]})
    right = pd.DataFrame({"kund_id": [1, 2, 3]})
    best = best_join(left, right)
    assert best is not None
    assert best.is_recommended
    assert best.left_column == "kund_id"


def test_shared_date_column_is_downgraded():
    """En datumkolumn med identiska värden är inte en nyckel."""
    ids = [1, 2, 3]
    left = pd.DataFrame({"datum": ["2024-01-01", "2024-01-02", "2024-01-03"], "kund_id": ids})
    right = pd.DataFrame({"datum": ["2024-01-01", "2024-01-02", "2024-01-03"], "kund_id": ids})
    best = best_join(left, right)
    assert best is not None
    assert best.left_column == "kund_id", "id-kolumnen ska vinna över datumkolumnen"


def test_measure_column_scores_lower_than_id_column():
    left = pd.DataFrame({"id": [1, 2, 3], "belopp": [10, 20, 30]})
    right = pd.DataFrame({"id": [1, 2, 3], "belopp": [10, 20, 30]})
    scores = {c.left_column: c.score for c in rank_join_candidates(left, right)}
    assert scores["id"] > scores["belopp"]


def test_many_to_many_without_unique_side_is_penalised():
    left = pd.DataFrame({"grupp": [1, 1, 2, 2]})
    right = pd.DataFrame({"grupp": [1, 1, 2, 2]})
    candidate = score_candidate(compare_keys(left["grupp"], right["grupp"]))
    assert not candidate.is_recommended
    assert any("många-till-många" in r for r in candidate.reasons)


def test_no_shared_values_is_unlikely():
    left = pd.DataFrame({"id": [1, 2, 3]})
    right = pd.DataFrame({"id": [7, 8, 9]})
    candidate = score_candidate(compare_keys(left["id"], right["id"]))
    assert candidate.verdict == "osannolik"


def test_type_mismatch_columns_are_excluded():
    left = pd.DataFrame({"k": [1, 2, 3]})
    right = pd.DataFrame({"k": ["1", "2", "3"]})
    assert rank_join_candidates(left, right) == []


def test_reasons_explain_the_verdict():
    left = pd.DataFrame({"kund_id": [1, 2, 3]})
    right = pd.DataFrame({"kund_id": [1, 2, 3]})
    best = best_join(left, right)
    assert any("unik" in r for r in best.reasons)
    assert any("täckning" in r for r in best.reasons)


def test_orphans_are_reported_in_reasons():
    left = pd.DataFrame({"kund_id": [1, 2, 9]})
    right = pd.DataFrame({"kund_id": [1, 2, 3]})
    best = best_join(left, right)
    assert any("saknar match" in r for r in best.reasons)
