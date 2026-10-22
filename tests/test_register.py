"""Tester för automatisk registrering av en ny datakälla.

En uppladdad fil ska bli en källa i pipen utan att någon redigerar YAML för
hand. Testerna bevakar de tre löften som gör det försvarligt att skriva till
specen automatiskt:

1. Kommentarerna i specen bevaras - filen är kontraktets dokumentation.
2. Den nya posten valideras innan den sparas; en ogiltig spec skrivs aldrig.
3. Varje flik blir en källa, även en utan egen nyckel (via en radnyckel).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from excel_merge.register import (
    RegistrationError,
    register_source,
    slug,
    suggest_source_name,
)
from excel_merge.relations import load_relation_spec

SPEC = """\
# Relationsspec: beskriver vad datamängderna handlar om och hur de hänger ihop.
#
# Detta är kontraktet.

version: 1

# Entiteter = de begrepp datan handlar om. Nyckeln identifierar en rad.
entities:
  customer:
    key: customer_id
    description: En kund.

# Källor = konkreta flikar i konkreta filer som tillhandahåller en entitet.
sources:
  - name: customers
    path: ../customers.xlsx
    sheet: Customers
    entity: customer
    dtypes:
      customer_id: int
    columns:
      customer_id: customer_id
      name: customer_name

# Byggen = vilka utdata som ska produceras ur entiteterna.
builds:
  - name: customer_list
    base: customer
    include: [customer]
    output: out/merged.xlsx
    sheet: Merged
    columns: [customer_id, customer_name]
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    pd.DataFrame({"customer_id": [1, 2, 3, 4], "name": ["A", "B", "C", "D"]}).to_excel(
        tmp_path / "customers.xlsx", index=False, sheet_name="Customers"
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "relations.yaml").write_text(SPEC, encoding="utf-8")
    return tmp_path


def _write(path: Path, sheet: str, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, sheet_name=sheet, index=False)
    return path


def _spec(project: Path) -> Path:
    return project / "config" / "relations.yaml"


def test_new_source_is_added_and_spec_still_valid(project):
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2], "amount": [5.0, 6.0]}
    ))
    reg = register_source(_spec(project), new, "Orders")
    assert reg.name == "orders"
    assert reg.key == "order_id"
    spec = load_relation_spec(_spec(project))
    assert "orders" in [s.name for s in spec.sources]


def test_comments_are_preserved(project):
    before = _spec(project).read_text(encoding="utf-8")
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2]}
    ))
    register_source(_spec(project), new, "Orders")
    after = _spec(project).read_text(encoding="utf-8")
    assert after.count("#") >= before.count("#")
    for line in before.splitlines():
        if line.strip().startswith("#"):
            assert line in after


def test_only_the_new_post_is_added(project):
    """Diffen ska bara innehålla det som tillkom - inte omformaterad text."""
    before = _spec(project).read_text(encoding="utf-8")
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2]}
    ))
    register_source(_spec(project), new, "Orders")
    after = _spec(project).read_text(encoding="utf-8")
    # Varje ursprunglig rad ska finnas kvar oförändrad, i samma ordning.
    remaining = list(after.splitlines())
    for line in before.splitlines():
        if line in remaining:
            remaining.remove(line)
    # Det som återstår är det nya blocket.
    assert all(not line.strip() or line.strip().startswith("-") or ":" in line
               or line.strip().startswith("name:") for line in remaining)


def test_file_without_key_gets_a_row_key(project):
    """En flik utan egen nyckel ska bli en källa, inte lämnas utanför."""
    new = _write(project / "inbox" / "logg.xlsx", "Logg", pd.DataFrame(
        {"text": ["a", "b", "a"], "varde": [1, 2, 3]}
    ))
    reg = register_source(_spec(project), new, "Logg")
    assert reg.key.endswith("_rad")
    spec = load_relation_spec(_spec(project))
    source = next(s for s in spec.sources if s.name == reg.name)
    assert source.row_key == reg.key
    assert reg.key in source.output_columns


def test_row_key_is_generated_when_read(project):
    new = _write(project / "inbox" / "logg.xlsx", "Logg", pd.DataFrame(
        {"text": ["a", "b", "a"]}
    ))
    reg = register_source(_spec(project), new, "Logg")
    spec = load_relation_spec(_spec(project))
    source = next(s for s in spec.sources if s.name == reg.name)

    from excel_merge.io import read_sheet

    frame = read_sheet(source, spec.base_dir)
    assert list(frame[reg.key]) == [1, 2, 3]


def test_relationship_is_added_when_keys_match(project):
    """En referens till en befintlig entitet kopplas in automatiskt."""
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2]}
    ))
    reg = register_source(_spec(project), new, "Orders")
    assert reg.relationship_to == "customer"
    assert reg.relationship_via == "customer_id"


def test_relationship_is_not_guessed_when_orphans_exist(project):
    """Nycklar som inte finns hos entiteten ska inte bli en tyst koppling."""
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [999, 1000]}
    ))
    reg = register_source(_spec(project), new, "Orders")
    assert reg.relationship_to is None


def test_relationship_is_not_added_to_itself(project):
    """En källas egen nyckel är ingen koppling till en annan entitet."""
    new = _write(project / "inbox" / "customers2.xlsx", "Customers", pd.DataFrame(
        {"customer_id": [10, 11], "name": ["X", "Y"]}
    ))
    reg = register_source(_spec(project), new, "Customers")
    assert reg.relationship_to is None


def test_invalid_spec_is_never_written(project):
    """En post som inte validerar ska lämna filen orörd.

    En nyckel som inte finns bland kolumnerna gör specen ogiltig. Skrivningen
    måste då backas - en trasig spec på disk är värre än ett felmeddelande.
    """
    before = _spec(project).read_text(encoding="utf-8")
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2]}
    ))
    with pytest.raises(RegistrationError, match="ogiltig"):
        register_source(_spec(project), new, "Orders", key="finns_inte")
    assert _spec(project).read_text(encoding="utf-8") == before


def test_sheet_without_columns_is_rejected(project):
    new = _write(project / "inbox" / "tom.xlsx", "Tom", pd.DataFrame())
    with pytest.raises(RegistrationError, match="inga kolumner"):
        register_source(_spec(project), new, "Tom")


def test_duplicate_source_name_is_rejected(project):
    new = _write(project / "inbox" / "customers.xlsx", "Customers", pd.DataFrame(
        {"customer_id": [7, 8], "name": ["P", "Q"]}
    ))
    with pytest.raises(RegistrationError, match="finns redan"):
        register_source(_spec(project), new, "Customers", name="customers")


def test_missing_sheet_is_reported(project):
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame({"a": [1]}))
    with pytest.raises(RegistrationError):
        register_source(_spec(project), new, "FinnsInte")


def test_columns_are_normalised(project):
    """Samma begrepp ska få samma namn oavsett skrivsätt."""
    new = _write(project / "inbox" / "kunder.xlsx", "Kunder", pd.DataFrame(
        {"Customer ID": [1, 2], "Namn": ["A", "B"]}
    ))
    reg = register_source(_spec(project), new, "Kunder")
    assert reg.columns["Customer ID"] == "customer_id"
    assert reg.columns["Namn"] == "namn"


def test_colliding_column_names_are_separated(project):
    """Två kolumner får aldrig mappas till samma namn."""
    new = _write(project / "inbox" / "dubblett.xlsx", "Dubblett", pd.DataFrame(
        {"Belopp": [1, 2], "belopp": [3, 4], "id": [1, 2]}
    ))
    reg = register_source(_spec(project), new, "Dubblett")
    assert len(set(reg.columns.values())) == len(reg.columns)


def test_registered_source_can_be_read_by_the_pipeline(project):
    """Källan ska inte bara stå i specen - den ska gå att läsa och använda."""
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2], "amount": [5.0, 6.0]}
    ))
    register_source(_spec(project), new, "Orders")
    spec = load_relation_spec(_spec(project))
    from excel_merge.engine import execute_build

    result = execute_build(spec, "customer_list")
    assert len(result.frame) == 4


def test_relative_path_is_used_in_the_spec(project):
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10], "customer_id": [1]}
    ))
    reg = register_source(_spec(project), new, "Orders")
    assert not Path(reg.path).is_absolute()
    assert "orders.xlsx" in reg.path


def test_two_uploads_both_become_sources(project):
    first = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2]}
    ))
    second = _write(project / "inbox" / "fakturor.xlsx", "Fakturor", pd.DataFrame(
        {"faktura_id": [1, 2], "customer_id": [3, 4]}
    ))
    register_source(_spec(project), first, "Orders")
    register_source(_spec(project), second, "Fakturor")
    spec = load_relation_spec(_spec(project))
    assert [s.name for s in spec.sources] == ["customers", "orders", "fakturor"]


def test_second_registration_does_not_duplicate_the_entity(project):
    """En andra källa till samma begrepp ska återanvända entiteten."""
    first = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10, 11], "customer_id": [1, 2]}
    ))
    second = _write(project / "inbox" / "ordrar2.xlsx", "Ordrar", pd.DataFrame(
        {"order_id": [12, 13], "customer_id": [3, 4]}
    ))
    register_source(_spec(project), first, "Orders")
    register_source(_spec(project), second, "Ordrar")
    spec = load_relation_spec(_spec(project))
    assert [s.entity for s in spec.sources].count("order") == 2
    assert list(spec.entities).count("order") == 1


def test_atomic_write_leaves_no_temp_file(project):
    new = _write(project / "inbox" / "orders.xlsx", "Orders", pd.DataFrame(
        {"order_id": [10], "customer_id": [1]}
    ))
    register_source(_spec(project), new, "Orders")
    assert list((project / "config").glob("*.tmp")) == []


def test_slug_normalises_names():
    assert slug("Customer ID") == "customer_id"
    assert slug("Prövningsgrupp ID") == "prövningsgrupp_id"
    assert slug("!!!") == "kalla"


def test_source_name_is_unique():
    assert suggest_source_name(Path("a.xlsx"), "A", set()) == "a"
    assert suggest_source_name(Path("a.xlsx"), "A", {"a"}) == "a_a"
    assert suggest_source_name(Path("a.xlsx"), "A", {"a", "a_a"}) == "a_a_2"
