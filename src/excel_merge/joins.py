"""Rangordning av kopplingskandidater med förklaringar.

`profile.compare_keys` ger rå fakta: täckning, kardinalitet, föräldralösa.
Den här modulen lägger på en bedömning: vilken kandidat är troligast en riktig
nyckel, och varför. Bedömningen är avsiktligt förklarande, inte bara en siffra,
eftersom en människa ska kunna granska och invända.

Nyckelinsikten är att värdeöverlapp ensamt inte räcker. Två kolumner kan
överlappa till hundra procent och ändå inte vara samma begrepp - till exempel en
datumkolumn som råkar ha samma värden i båda tabellerna. Därför väger unikhet
och namnledtrådar tyngre än täckning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from excel_merge.profile import KeyComparison, compare_keys

# Ord som antyder att en kolumn är en identifierare. Längsta ordet först, så att
# "nummer" prövas före "nr" när en rot ska skalas av.
IDENTIFIER_HINTS = ("nummer", "beteckning", "nyckel", "code", "kod", "key", "id", "nr")

# Värden som antyder att kolumnen är ett mått eller en tidpunkt, inte en nyckel.
_MEASURE_HINTS = (
    "datum", "tidpunkt", "tid", "date", "time", "år", "ar", "belopp", "effekt",
    "antal", "amount", "sum", "total", "price", "pris", "värde", "varde",
    "quantity", "kvantitet",
)


def looks_like_measure(column: str) -> bool:
    """Säger om kolumnnamnet antyder ett mått eller en tidpunkt snarare än en nyckel.

    Används för att avgöra om en kolumn är värd att visa som nyckel. En kolumn
    kan vara unik i ett litet datamaterial av en slump - ett belopp eller ett
    datum är då unikt utan att vara en identifierare.
    """
    lowered = column.lower()
    return any(hint in lowered for hint in _MEASURE_HINTS)


def looks_like_identifier(column: str) -> bool:
    """Säger om kolumnnamnet antyder en identifierare.

    Matchningen är på *delsträng*, inte på avgränsade ord. Det är avgörande för
    svenska sammansättningar: ``Lanskod`` och ``Kundnummer`` innehåller "kod"
    respektive "nummer" utan understreck emellan. En ordgräns hade missat dem
    och låtit en måttkolumn vinna på bokstavsordning.

    Priset är att en kolumn som ``Arbetskod`` också räknas som identifierare.
    Det är en rimlig avvägning: heuristiken föreslår, en människa bekräftar.
    """
    lowered = column.lower()
    return any(hint in lowered for hint in IDENTIFIER_HINTS)


@dataclass(frozen=True)
class JoinCandidate:
    left_column: str
    right_column: str
    comparison: KeyComparison
    score: float
    verdict: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_recommended(self) -> bool:
        return self.verdict == "rekommenderad"


def _name_hint(column: str) -> int:
    if looks_like_identifier(column):
        return 15
    if looks_like_measure(column):
        return -25
    return 0


def _distinct_ratio(comparison: KeyComparison) -> float:
    """Hur stor andel av nycklarna som är unika, sett över båda sidor."""
    ratios = []
    for distinct, unique in (
        (comparison.left_distinct, comparison.left_unique),
        (comparison.right_distinct, comparison.right_unique),
    ):
        if distinct:
            ratios.append(1.0 if unique else 0.0)
    return sum(ratios) / len(ratios) if ratios else 0.0


def score_candidate(comparison: KeyComparison) -> JoinCandidate:
    reasons: list[str] = []
    score = 0.0

    if comparison.matched == 0:
        return JoinCandidate(
            comparison.left, comparison.right, comparison, 0.0, "osannolik",
            ["inga gemensamma värden alls"],
        )

    if comparison.left_unique or comparison.right_unique:
        score += 50
        side = "båda sidor" if comparison.left_unique and comparison.right_unique else (
            "vänster" if comparison.left_unique else "höger"
        )
        reasons.append(f"unik på {side} - kan identifiera en rad")

    if comparison.left_unique and comparison.right_unique:
        score += 10
        reasons.append("1:1 mellan tabellerna")

    min_coverage = min(comparison.coverage_left, comparison.coverage_right)
    score += min_coverage * 30
    reasons.append(f"täckning {min_coverage:.0%} i sämsta riktningen")

    hint = _name_hint(comparison.left)
    if hint:
        score += hint
        if hint > 0:
            reasons.append("kolumnnamnet antyder en identifierare")
        else:
            reasons.append("kolumnnamnet antyder ett mått eller en tidpunkt")

    if not comparison.left_unique and not comparison.right_unique:
        score -= 20
        reasons.append("många-till-många utan unik sida - troligen inte en nyckel")

    if comparison.orphans_left == 0 and comparison.orphans_right == 0:
        score += 10
        reasons.append("alla nycklar matchar i båda riktningar")
    else:
        reasons.append(
            f"{comparison.orphans_left} nycklar saknar match till vänster, "
            f"{comparison.orphans_right} till höger"
        )

    if comparison.left_nulls or comparison.right_nulls:
        score -= 10
        reasons.append(
            f"nollvärden i nyckeln (vänster {comparison.left_nulls}, höger {comparison.right_nulls})"
        )

    if score >= 70:
        verdict = "rekommenderad"
    elif score >= 45:
        verdict = "möjlig"
    else:
        verdict = "osannolik"

    return JoinCandidate(
        comparison.left, comparison.right, comparison, round(score, 1), verdict, reasons
    )


def rank_join_candidates(
    left: pd.DataFrame,
    right: pd.DataFrame,
    min_coverage: float = 0.1,
) -> list[JoinCandidate]:
    """Rangordna kolumnpar efter hur troligt det är att de är samma nyckel.

    Kolumner med typkrock utesluts, eftersom de ändå inte kan kopplas utan
    konvertering. Övriga kandidater sorteras med bäst först.
    """
    shared = [c for c in left.columns if c in right.columns]
    candidates = []
    for column in shared:
        comparison = compare_keys(left[column], right[column])
        if comparison.type_mismatch:
            continue
        if min(comparison.coverage_left, comparison.coverage_right) < min_coverage:
            continue
        candidates.append(score_candidate(comparison))
    return sorted(candidates, key=lambda c: c.score, reverse=True)


def best_join(left: pd.DataFrame, right: pd.DataFrame) -> JoinCandidate | None:
    candidates = rank_join_candidates(left, right)
    return candidates[0] if candidates else None
