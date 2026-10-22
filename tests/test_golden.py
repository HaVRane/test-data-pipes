"""Golden-file-test: låser hela utdata för standardflödet.

Ändrar man flödet medvetet uppdaterar man filen med:
    UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py
Diffen blir då synlig i git, vilket är precis vad en granskande agent behöver se.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from excel_merge.config import load_config
from excel_merge.pipeline import merge_sources

GOLDEN = Path(__file__).parent / "golden" / "merged_left.csv"


def _canonical(frame: pd.DataFrame) -> pd.DataFrame:
    """Gör utdata jämförbar mellan pandas-objekt och CSV (t.ex. datum)."""
    frame = frame.reset_index(drop=True).copy()
    for column in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            frame[column] = frame[column].dt.strftime("%Y-%m-%d")
    return frame


def test_output_matches_golden(make_config):
    result = _canonical(merge_sources(load_config(make_config(how="left"))))

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
