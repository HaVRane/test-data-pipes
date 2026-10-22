"""Kommandoradsgränssnitt: python -m excel_merge.cli --config config/pipeline.yaml"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from excel_merge.config import ConfigError, load_config
from excel_merge.io import SourceReadError
from excel_merge.pipeline import PipelineError, run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Koppla ihop Excel-flikar till ett nytt ark.")
    parser.add_argument("--config", required=True, type=Path, help="Sökväg till pipeline-konfigurationen (YAML)")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        result = run_pipeline(config)
    except (ConfigError, SourceReadError, PipelineError) as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1

    for name, rows in result.row_counts.items():
        print(f"  läste {name}: {rows} rader")
    print(f"  skrev {len(result.frame)} rader till {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
