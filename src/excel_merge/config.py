"""Delade datastrukturer för utdata.

Bara det som är gemensamt mellan relationslagret och I/O-lagret bor här, så att
io.py inte behöver känna till hela relationsmodellen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutputConfig:
    path: Path
    sheet: str
    columns: list[str] | None = None


class ConfigError(ValueError):
    """Konfigurationen är strukturellt felaktig eller inkonsekvent."""
