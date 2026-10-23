"""Deterministiska testfixtures.

Bygger Excel-arbetsböcker programmatiskt i stället för att checka in binära
filer. Varje test får exakt samma indata varje gång, och en agent kan läsa
fixturen som kod när den ska lägga till en ny källa.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CUSTOMERS = pd.DataFrame(
    {
        "customer_id": [1, 2, 3, 4],
        "name": ["Acme AB", "Beta KB", "Gamma HB", "Delta AB"],
        "segment": ["Enterprise", "SMB", "SMB", "Enterprise"],
    }
)

# Unik kund per orderrad (many_to_one) + en order för okänd kund (id 5).
ORDERS = pd.DataFrame(
    {
        "order_id": [101, 102, 103, 104],
        "customer_id": [1, 2, 4, 5],
        "amount": [100.5, 200.0, 75.25, 999.0],
        "order_date": pd.to_datetime(["2024-01-05", "2024-01-10", "2024-03-15", "2024-03-20"]),
    }
)


def write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet, index=False)
    return path


def build_sample_sources(directory: Path) -> tuple[Path, Path]:
    """Skriv de två standardkällorna och returnera deras sökvägar."""
    customers = write_workbook(directory / "customers.xlsx", {"Customers": CUSTOMERS})
    orders = write_workbook(directory / "orders.xlsx", {"Orders": ORDERS})
    return customers, orders
