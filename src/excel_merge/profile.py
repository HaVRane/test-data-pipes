"""Profilering av datamängder: underlag för att föreslå hur källor kopplas ihop.

Detta är verktyget en agent kör *innan* den skriver en relationsspec. Det svarar
på de tre frågor som avgör om en koppling är rimlig:

1. Vilka kolumner kan fungera som nyckel (typ, unikhet, nollvärden)?
2. Hur väl överlappar nycklarna mellan källorna (täckning, föräldralösa nycklar)?
3. Vilken kardinalitet har relationen (1:1, 1:många, många:1, många:många)?

Verktyget *föreslår*, det beslutar inte. Utdata är avsiktligt formulerad som
bevis en människa kan granska, plus ett utkast till spec-post.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

_NUMERIC = "numeric"
_DATETIME = "datetime"
_TEXT = "text"


def column_kind(series: pd.Series) -> str:
    """Klassar en kolumn som numeric, datetime eller text.

    Publik för att kunna återanvändas: ämnesområdeshärledningen avgör om en
    kolumn är ett mått eller ett attribut med samma typning som profileringen.
    """
    if pd.api.types.is_bool_dtype(series):
        return _TEXT
    if pd.api.types.is_numeric_dtype(series):
        return _NUMERIC
    if pd.api.types.is_datetime64_any_dtype(series):
        return _DATETIME
    return _TEXT


def _kind(series: pd.Series) -> str:
    return column_kind(series)


def _canonical(series: pd.Series) -> pd.Series:
    """Gör värden jämförbara över typer så att t.ex. int 1 och float 1.0 matchar."""
    kind = _kind(series)
    values = series.dropna()
    if kind == _NUMERIC:
        return values.astype("float64")
    if kind == _DATETIME:
        return values.astype("datetime64[ns]")
    return values.astype("string").str.strip()


@dataclass(frozen=True)
class ColumnStats:
    name: str
    dtype: str
    rows: int
    nulls: int
    distinct: int
    is_unique: bool
    sample: list[object] = field(default_factory=list)

    @property
    def null_rate(self) -> float:
        return self.nulls / self.rows if self.rows else 0.0

    @property
    def is_candidate_key(self) -> bool:
        return self.nulls == 0 and self.is_unique


def column_stats(series: pd.Series, name: str | None = None, sample_size: int = 3) -> ColumnStats:
    values = series.dropna()
    return ColumnStats(
        name=str(name if name is not None else series.name),
        dtype=str(series.dtype),
        rows=len(series),
        nulls=int(series.isna().sum()),
        distinct=int(values.nunique()),
        is_unique=len(values) == values.nunique() and int(series.isna().sum()) == 0,
        sample=list(values.head(sample_size)),
    )


@dataclass(frozen=True)
class KeyComparison:
    left: str
    right: str
    left_distinct: int
    right_distinct: int
    matched: int
    orphans_left: int
    orphans_right: int
    left_unique: bool
    right_unique: bool
    left_nulls: int
    right_nulls: int
    type_mismatch: bool

    @property
    def coverage_left(self) -> float:
        """Andel av vänstra sidans nycklar som finns hos den högra."""
        return self.matched / self.left_distinct if self.left_distinct else 0.0

    @property
    def coverage_right(self) -> float:
        return self.matched / self.right_distinct if self.right_distinct else 0.0

    @property
    def cardinality(self) -> str:
        if self.left_unique and self.right_unique:
            return "one_to_one"
        if self.left_unique:
            return "one_to_many"
        if self.right_unique:
            return "many_to_one"
        return "many_to_many"

    @property
    def is_plausible_join(self) -> bool:
        return self.matched > 0 and not self.type_mismatch


def compare_keys(left: pd.Series, right: pd.Series) -> KeyComparison:
    left_canonical = _canonical(left)
    right_canonical = _canonical(right)

    left_set = set(left_canonical)
    right_set = set(right_canonical)
    matched = left_set & right_set

    return KeyComparison(
        left=str(left.name),
        right=str(right.name),
        left_distinct=len(left_set),
        right_distinct=len(right_set),
        matched=len(matched),
        orphans_left=len(left_set - right_set),
        orphans_right=len(right_set - left_set),
        left_unique=column_stats(left).is_unique,
        right_unique=column_stats(right).is_unique,
        left_nulls=int(left.isna().sum()),
        right_nulls=int(right.isna().sum()),
        type_mismatch=_kind(left) != _kind(right),
    )


def discover_candidate_keys(
    left: pd.DataFrame,
    right: pd.DataFrame,
    min_coverage: float = 0.5,
) -> list[KeyComparison]:
    """Hitta kolumnpar mellan två datamängder som ser ut som kopplingsnycklar.

    Ett par är kandidat om nycklarna överlappar tillräckligt och typerna inte
    uppenbart krockar. Resultatet sorteras på täckning, bäst först.
    """
    shared = [c for c in left.columns if c in right.columns]
    comparisons = [compare_keys(left[c], right[c]) for c in shared]
    plausible = [
        c
        for c in comparisons
        if c.matched > 0
        and min(c.coverage_left, c.coverage_right) >= min_coverage
        and not c.type_mismatch
    ]
    return sorted(plausible, key=lambda c: min(c.coverage_left, c.coverage_right), reverse=True)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def format_comparison(comparison: KeyComparison) -> str:
    lines = [
        f"  nyckel: {comparison.left} <-> {comparison.right}",
        f"    distinkta nycklar: vänster {comparison.left_distinct}, höger {comparison.right_distinct}",
        f"    matchade: {comparison.matched} "
        f"(täckning vänster {_pct(comparison.coverage_left)}, höger {_pct(comparison.coverage_right)})",
        f"    föräldralösa: vänster {comparison.orphans_left}, höger {comparison.orphans_right}",
        f"    nollvärden i nyckel: vänster {comparison.left_nulls}, höger {comparison.right_nulls}",
        f"    unik: vänster {comparison.left_unique}, höger {comparison.right_unique}",
        f"    föreslagen kardinalitet: {comparison.cardinality}",
    ]
    if comparison.type_mismatch:
        lines.append("    VARNING: olika kolumntyper - kontrollera att värdena betyder samma sak")
    return "\n".join(lines)


def suggest_spec_entry(comparison: KeyComparison, target_entity: str) -> str:
    """Emitting a draft spec entry.

    Förslaget är medvetet kommenterat: kardinalitet och orphaning-policy är
    affärsbeslut som en människa måste bekräfta innan posten är giltig.
    """
    orphans = comparison.orphans_left
    orphan_word = "nyckel" if orphans == 1 else "nycklar"
    orphan_note = (
        f"# {orphans} {orphan_word} saknar match på andra sidan - "
        "ska de släppas, flaggas eller fyllas?"
    )
    return "\n".join(
        [
            "    relationships:",
            f"      - to: {target_entity}",
            f"        via: {comparison.left}",
            f"        target_key: {comparison.right}",
            f"        cardinality: {comparison.cardinality}  # maskinellt föreslagen - bekräfta mot verksamheten",
            f"        {orphan_note}",
        ]
    )


def profile_pair(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_key: str,
    right_key: str,
) -> KeyComparison:
    if left_key not in left.columns:
        raise KeyError(f"kolumnen '{left_key}' finns inte i vänstra datamängden: {list(left.columns)}")
    if right_key not in right.columns:
        raise KeyError(f"kolumnen '{right_key}' finns inte i högra datamängden: {list(right.columns)}")
    return compare_keys(left[left_key], right[right_key])
