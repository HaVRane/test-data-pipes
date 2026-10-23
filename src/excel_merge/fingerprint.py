"""Innehållsfingeravtryck för en datakälla.

För att kunna säga "källan har ändrats" måste vi veta vad källan innehöll
förra gången. Ett fingeravtryck är en hash av *innehållet*, inte av filen.

Varför inte filhash: Excel skriver om hela arkivet varje gång filen sparas,
även om ingen uppgift ändrats. En filhash skulle därför larma varje gång någon
öppnar och stänger filen. Innehållshashen är stabil så länge datan är stabil.

Fingeravtrycket är avsiktligt känsligt för radordning och kolumnordning: att
sortera om raderna är en ändring av källan som är värd att känna till.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

_MISSING = ""


def canonical_cell(value: Any) -> str:
    """Gör ett cellvärde till en stabil sträng.

    Normaliseringen är till för att undvika falska ändringar. Excel ger ofta
    samma uppgift olika Python-typ mellan två läsningar: talet 1 kan komma som
    int eller float, och ett tal kan komma som text. De varianterna ska ge samma
    fingeravtryck, annars larmar loggen om ändringar som inte finns.
    """
    if value is None:
        return _MISSING
    if isinstance(value, (list, tuple, dict, set)):
        return str(value)

    try:
        if pd.isna(value):
            return _MISSING
    except (TypeError, ValueError):
        pass

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (pd.Timestamp, _dt.datetime, _dt.date)):
        stamp = pd.Timestamp(value)
        # Datum utan klockslag normaliseras till datum, så att midnatt och
        # ett rent datum inte ger olika fingeravtryck.
        if stamp.hour == stamp.minute == stamp.second == 0 and stamp.nanosecond == 0:
            return stamp.date().isoformat()
        return stamp.isoformat()

    if isinstance(value, float):
        if math.isnan(value):
            return _MISSING
        if value.is_integer():
            return str(int(value))
        return repr(value)

    if isinstance(value, int):
        return str(value)

    text = str(value).strip()
    # Text som ser ut som ett heltal behandlas som talet.
    if text and (text.lstrip("-").isdigit()):
        return str(int(text))
    return text


@dataclass(frozen=True)
class SourceFingerprint:
    """Ett ögonblicksbild av en källas innehåll."""

    digest: str
    rows: int
    columns: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"fingerprint": self.digest, "rows": self.rows, "columns": list(self.columns)}


def fingerprint_frame(frame: pd.DataFrame) -> SourceFingerprint:
    """Beräkna innehållsfingeravtryck för en tabell."""
    columns = [str(c).strip() for c in frame.columns]
    hasher = hashlib.sha256()

    hasher.update(b"columns\x00")
    for column in columns:
        hasher.update(column.encode("utf-8"))
        hasher.update(b"\x00")

    hasher.update(b"rows\x00")
    for row in frame.itertuples(index=False, name=None):
        for cell in row:
            hasher.update(canonical_cell(cell).encode("utf-8"))
            hasher.update(b"\x1f")
        hasher.update(b"\x1e")

    return SourceFingerprint(digest="sha256:" + hasher.hexdigest(), rows=len(frame), columns=columns)
