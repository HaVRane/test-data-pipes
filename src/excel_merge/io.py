"""Läsning och skrivning av Excel, isolerat från affärslogiken.

Allt I/O går genom dessa funktioner. Det gör att testerna kan arbeta mot
temporära filer utan att känna till pandas detaljer.

read_sheet tar emot vad som helst med attributen path, sheet, name,
required_input_columns, columns och dtypes - både SourceSpec och enklare
testdubblar. Det håller I/O-lagret fritt från relationsmodellen.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from excel_merge.config import OutputConfig


class SourceReadError(RuntimeError):
    """En källa kunde inte läsas som förväntat."""


class SourceMissingError(SourceReadError):
    """Källans fil eller flik finns inte.

    Detta är inte ett läsproblem utan en frånvaro: källan finns inte längre.
    Skillnaden styr modellen - en saknad källa tas bort precis som om posten
    strukits ur specen, medan en oläsbar fil finns kvar men inte kan tolkas.
    """


def resolve_source_path(source, base_dir: Path) -> Path:
    """Sökvägen till källans fil, absolut."""
    return source.path if source.path.is_absolute() else (base_dir / source.path).resolve()


def source_is_present(source, base_dir: Path) -> bool:
    """Säger om källans fil och flik finns.

    En fil som inte går att öppna alls räknas som närvarande. Vi kan inte veta
    om fliken finns i en trasig fil, och en trasig fil är ett läsproblem - inte
    en frånvaro. ``read_sheet`` rapporterar det med sitt eget meddelande.
    """
    path = resolve_source_path(source, base_dir)
    if not path.is_file():
        return False
    try:
        with pd.ExcelFile(path, engine="openpyxl") as book:
            return source.sheet in book.sheet_names
    except Exception:
        return True


def read_raw_sheet(source, base_dir: Path) -> pd.DataFrame:
    """Läs hela fliken utan projektion eller typning.

    Används för att upptäcka ändringar i källan, eftersom även kolumner som
    specen inte använder ingår i jämförelsen.
    """
    path = resolve_source_path(source, base_dir)
    if not path.is_file():
        raise SourceMissingError(f"källan '{source.name}': filen hittades inte: {path}")

    try:
        df = pd.read_excel(path, sheet_name=source.sheet, engine="openpyxl")
    except ValueError as exc:  # openpyxl/pandas kastar ValueError för okänd flik
        try:
            available = pd.ExcelFile(path, engine="openpyxl").sheet_names
        except Exception:
            available = []
        if available:
            raise SourceMissingError(
                f"källan '{source.name}': fliken '{source.sheet}' finns inte i {path.name}. "
                f"Tillgängliga flikar: {available}"
            ) from exc
        # Filen gick inte att öppna alls. Det är ett läsproblem, inte en frånvaro.
        raise SourceReadError(
            f"källan '{source.name}': kunde inte läsas ({type(exc).__name__}: {exc})"
        ) from exc
    except Exception as exc:  # trasig eller felformad fil ska bli ett läsbart fel
        raise SourceReadError(
            f"källan '{source.name}': kunde inte läsas ({type(exc).__name__}: {exc})"
        ) from exc

    df.columns = [str(c).strip() for c in df.columns]
    return df


def read_sheet(source, base_dir: Path) -> pd.DataFrame:
    df = read_raw_sheet(source, base_dir)

    missing = [c for c in source.required_input_columns if c not in df.columns]
    if missing:
        raise SourceReadError(
            f"källan '{source.name}': kolumn(er) {missing} saknas i fliken '{source.sheet}'. "
            f"Fliken har: {list(df.columns)}"
        )

    df = df[source.required_input_columns].copy()
    df = df.rename(columns=source.columns)

    for column, dtype in source.dtypes.items():
        target = source.columns.get(column, column)
        try:
            df[target] = df[target].astype(dtype)
        except (TypeError, ValueError) as exc:
            raise SourceReadError(
                f"källan '{source.name}': kunde inte typa kolumnen '{target}' som {dtype}: {exc}"
            ) from exc

    return df


def write_sheet(df: pd.DataFrame, output: OutputConfig, base_dir: Path) -> Path:
    path = output.path if output.path.is_absolute() else (base_dir / output.path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=output.sheet, index=False)
    return path
