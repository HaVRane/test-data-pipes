"""Inventera uppladdade arbetsböcker och föreslå spec-poster.

Verktyget är gjort för arbetsflödet "ladda upp en fil i taget": peka det på en
katalog så listar det varje arbetsbok och varje flik, profilerar kolumnerna och
föreslår hur fliken kan beskrivas som källa i relationsspecen.

Det läser bara och skriver inget till specen. Tanken är att man klistrar in
utkastet och sedan bekräftar kardinalitet och orphaning-policy mot verksamheten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from excel_merge.joins import is_key_candidate
from excel_merge.profile import column_stats, format_comparison, discover_candidate_keys

SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls"}


def find_workbooks(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"katalogen finns inte: {directory}")
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SPREADSHEET_SUFFIXES
    )


def _slug(text: str) -> str:
    """Gör ett fliknamn till ett användbart källnamn i specen."""
    cleaned = [c if c.isalnum() else "_" for c in text.strip().lower()]
    slug = "".join(cleaned).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "kalla"


def describe_workbook(path: Path) -> list[tuple[str, pd.DataFrame]]:
    """Läs alla flikar i en arbetsbok utan att anta något om innehållet."""
    with pd.ExcelFile(path, engine="openpyxl") as book:
        return [(name, pd.read_excel(book, sheet_name=name)) for name in book.sheet_names]


def suggest_source_entry(path: Path, sheet: str, frame: pd.DataFrame) -> str:
    """Föreslå ett sources-block i relationsspecen för en flik."""
    columns = {str(c).strip(): _slug(str(c)) for c in frame.columns}
    name = _slug(sheet)
    lines = [
        "  - name: " + name,
        "    path: ../" + str(path).replace("\\", "/"),
        "    sheet: " + sheet,
        "    entity: " + name + "        # sätt till rätt entitet",
        "    columns:",
    ]
    lines += [f"      {original}: {target}" for original, target in columns.items()]
    return "\n".join(lines)


def report(directory: Path, reference: Path | None = None) -> int:
    workbooks = find_workbooks(directory)
    if not workbooks:
        print(f"Inga arbetsböcker hittades i {directory}")
        return 1

    reference_frame: pd.DataFrame | None = None
    if reference is not None:
        reference_frame = pd.read_excel(reference, sheet_name=0, engine="openpyxl")

    print(f"Hittade {len(workbooks)} arbetsbok(er) i {directory}:\n")
    for path in workbooks:
        print(f"=== {path} ===")
        for sheet, frame in describe_workbook(path):
            print(f"\n  flik '{sheet}': {len(frame)} rader, {len(frame.columns)} kolumner")
            for column in frame.columns:
                stats = column_stats(frame[column], name=str(column))
                marker = "  <- möjlig nyckel" if is_key_candidate(frame, column) else ""
                print(
                    f"    {stats.name}: typ={stats.dtype}, distinkta={stats.distinct}, "
                    f"nollvärden={stats.nulls}{marker}"
                )

            if reference_frame is not None:
                candidates = discover_candidate_keys(frame, reference_frame)
                if candidates:
                    print("    kandidatkoppling mot referensen:")
                    print(format_comparison(candidates[0]))

            print("\n    utkast till spec-post:")
            for line in suggest_source_entry(path, sheet, frame).splitlines():
                print("    " + line)
        print()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventera uppladdade Excel-filer och föreslå spec-poster.")
    parser.add_argument("directory", type=Path, help="Katalog att leta arbetsböcker i, t.ex. data/isa")
    parser.add_argument("--reference", type=Path, help="Befintlig flik att jämföra nycklar mot")
    args = parser.parse_args(argv)
    try:
        return report(args.directory, args.reference)
    except FileNotFoundError as exc:
        print(f"FEL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
