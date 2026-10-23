"""Skapa exempeldata i data/ så flödet kan köras manuellt."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fixtures import build_sample_sources  # noqa: E402

if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "data"
    build_sample_sources(target)
    print(f"Exempeldata skriven till {target}")
