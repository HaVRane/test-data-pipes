"""Tester för rangordning av kopplingskandidater."""

from __future__ import annotations

import pandas as pd

from excel_merge.joins import (
    best_join,
    looks_like_identifier,
    looks_like_measure,
    rank_join_candidates,
    score_candidate,
)
from excel_merge.profile import compare_keys


def test_unique_id_column_is_recommended():
    left = pd.DataFrame({"kund_id": [1, 2, 3]})
    right = pd.DataFrame({"kund_id": [1, 2, 3]})
    best = best_join(left, right)
    assert best is not None
    assert best.is_recommended
    assert best.left_column == "kund_id"


def test_compound_swedish_words_are_identifiers():
    """Svenska sammansättningar ska kännas igen utan understreck.

    ``Lanskod`` och ``Kundnummer`` är vanliga kolumnnamn i svensk data. En
    matchning som kräver ordgräns missar dem och låter en måttkolumn vinna.
    """
    assert looks_like_identifier("Lanskod")
    assert looks_like_identifier("Kundnummer")
    assert looks_like_identifier("Ordernr")
    assert looks_like_identifier("customer_id")
    # Ett namn är ingen identifierare, och ett mått är det inte heller.
    assert not looks_like_identifier("Lansnamn")
    assert not looks_like_identifier("Befolkning_2025_12_31")
    assert not looks_like_identifier("belopp")


def test_time_columns_are_measures_not_identifiers():
    """En tidskolumn får inte bli nyckel, trots att "tid" innehåller "id".

    Delsträngsmatchningen för "id" träffar svenska ord som ``Tid`` och
    ``Aktivitetstid``. Utan måttfiltret hade en sådan kolumn fått högst prioritet
    och kunnat bli entitetsnyckel - samma slags tysta fel som Länsinfo-buggen.
    """
    assert looks_like_measure("Tid")
    assert looks_like_measure("Aktivitetstid")
    assert looks_like_measure("Tidszon")
    # Filtret för mått avgör saken, även om formen ser ut som en identifierare.
    assert looks_like_identifier("Aktivitetstid")


def test_time_column_is_excluded_from_candidate_keys():
    from excel_merge.register import _column_mapping, candidate_keys

    frame = pd.DataFrame({"Aktivitetstid": ["08:00", "09:00", "10:00"], "Kundnr": [1, 2, 3]})
    keys = candidate_keys(frame, _column_mapping(frame))
    assert keys == ["kundnr"], "tidskolumnen ska inte kunna bli nyckel"


def test_measure_and_identifier_are_separate_questions():
    """En kolumn kan vara både ett mått och bära en identitetsändelse.

    Frågorna besvaras var för sig: ``Arbetskod`` är en identifierare till formen,
    men innehållet kan vara ett mått. Filtret för mått avgör det senare.
    """
    assert looks_like_identifier("Arbetskod")
    assert looks_like_measure("Arbetskod")


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


def test_looks_like_measure_recognises_amounts_and_dates():
    from excel_merge.joins import looks_like_measure

    assert looks_like_measure("belopp")
    assert looks_like_measure("order_date")
    assert looks_like_measure("amount")
    assert not looks_like_measure("customer_id")
    assert not looks_like_measure("namn")
