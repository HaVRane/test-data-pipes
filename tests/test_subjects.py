"""Tester för härledda ämnesområden.

Härledningen är regelbaserad och deterministisk. Testerna bevakar att
klassningen blir rätt, att varje roll bär ett skäl, och att inget försvinner
tyst - en entitet som inte går att placera ska rapporteras, inte glömmas.

Det sista är samma princip som gäller för uppladdade filer: ingen får ignoreras.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from excel_merge.relations import load_relation_spec
from excel_merge.subjects import (
    derive_subjects,
    load_frames,
    subject_model_to_dict,
)

# order har mått och pekar på customer; customer beskriver bara.
TWO_ENTITIES = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
      segment: segment
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    dtypes:
      amount: float
    columns:
      order_id: order_id
      customer_id: customer_id
      amount: order_amount
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
        orphans: keep
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out.xlsx
    sheet: Out
"""

# Samma två entiteter, men utan deklarerade typer. Då avgör filens innehåll.
TWO_ENTITIES_UNTYPED = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
      segment: segment
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    columns:
      order_id: order_id
      customer_id: customer_id
      amount: order_amount
    relationships:
      - to: customer
        via: customer_id
        cardinality: many_to_one
        orphans: keep
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out.xlsx
    sheet: Out
"""

# Två fakta som delar customer: den blir en konform dimension.
TWO_FACTS = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
  invoice:
    key: invoice_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    dtypes:
      amount: float
    columns:
      order_id: order_id
      customer_id: customer_id
      amount: order_amount
    relationships:
      - to: customer
        via: customer_id
  - name: invoices
    path: i.xlsx
    sheet: S
    entity: invoice
    dtypes:
      total: float
    columns:
      invoice_id: invoice_id
      customer_id: customer_id
      total: invoice_total
    relationships:
      - to: customer
        via: customer_id
builds:
  - name: order_subject
    base: order
    include: [customer]
    output: o.xlsx
    sheet: S
  - name: invoice_subject
    base: invoice
    include: [customer]
    output: i.xlsx
    sheet: S
"""

# Ingen måttkolumn alls: då finns ingen fakta att mäta på.
NO_MEASURES = """\
version: 1
entities:
  customer:
    key: customer_id
  region:
    key: region_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
      region_id: region_id
    relationships:
      - to: region
        via: region_id
  - name: regions
    path: r.xlsx
    sheet: S
    entity: region
    columns:
      region_id: region_id
      region_name: region_name
builds:
  - name: customer_subject
    base: customer
    include: [region]
    output: out.xlsx
    sheet: S
"""

# En entitet med källa som inget bygge nämner.
UNASSIGNED = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
  lonely:
    key: lonely_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    dtypes:
      amount: float
    columns:
      order_id: order_id
      customer_id: customer_id
      amount: order_amount
    relationships:
      - to: customer
        via: customer_id
  - name: lonely
    path: l.xlsx
    sheet: S
    entity: lonely
    dtypes:
      value: float
    columns:
      lonely_id: lonely_id
      value: lonely_value
builds:
  - name: customer_orders
    base: customer
    include: [order]
    output: out.xlsx
    sheet: S
"""

# Två byggen men inget bygge alls: fallback till grafens komponenter.
NO_BUILDS = """\
version: 1
entities:
  customer:
    key: customer_id
  order:
    key: order_id
sources:
  - name: customers
    path: c.xlsx
    sheet: S
    entity: customer
    columns:
      customer_id: customer_id
      name: customer_name
  - name: orders
    path: o.xlsx
    sheet: S
    entity: order
    dtypes:
      amount: float
    columns:
      order_id: order_id
      customer_id: customer_id
      amount: order_amount
    relationships:
      - to: customer
        via: customer_id
"""


def _spec(tmp_path: Path, text: str):
    path = tmp_path / "r.yaml"
    path.write_text(text, encoding="utf-8")
    return load_relation_spec(path)


def _write(path: Path, sheet: str, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False, sheet_name=sheet)


def test_fact_and_dimension_are_separated(tmp_path):
    """Entiteten med mått blir fakta, den som bara beskriver blir dimension."""
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    subject = model.subjects[0]
    assert [f.entity for f in subject.facts] == ["order"]
    assert [d.entity for d in subject.dimensions] == ["customer"]


def test_measures_exclude_keys_and_foreign_keys(tmp_path):
    """Nycklar och främmande nycklar får aldrig bli mått, även när de är tal."""
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    measures = model.subjects[0].measures
    assert [m.column for m in measures] == ["order_amount"]
    assert "order_id" not in [m.column for m in measures]
    assert "customer_id" not in [m.column for m in measures]


def test_measure_carries_a_reason(tmp_path):
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    measure = model.subjects[0].measures[0]
    assert measure.reason
    assert "order_amount" in measure.reason or "amount" in measure.reason


def test_dimension_attributes_are_descriptive_columns(tmp_path):
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    dimension = model.subjects[0].dimensions[0]
    assert "customer_name" in dimension.attributes
    assert "segment" in dimension.attributes
    assert "customer_id" not in dimension.attributes


def test_foreign_key_is_reported_with_cardinality(tmp_path):
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    keys = model.subjects[0].facts[0].foreign_keys
    assert len(keys) == 1
    assert keys[0].to_entity == "customer"
    assert keys[0].cardinality == "many_to_one"


def test_subject_carries_a_reason(tmp_path):
    """Varje ämnesområde ska kunna förklara varför det finns."""
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    assert "customer_orders" in model.subjects[0].reason


def test_conformed_dimension_is_detected(tmp_path):
    """En dimension som två ämnesområden delar är konform."""
    model = derive_subjects(_spec(tmp_path, TWO_FACTS), frames={})
    assert [c.entity for c in model.conformed] == ["customer"]
    assert model.conformed[0].subjects == ["invoice_subject", "order_subject"]


def test_entity_used_once_is_not_conformed(tmp_path):
    model = derive_subjects(_spec(tmp_path, TWO_ENTITIES), frames={})
    assert model.conformed == []


def test_no_measures_means_no_fact(tmp_path):
    """Utan mått finns ingen fakta. Då får inget tvingas in i rollen."""
    model = derive_subjects(_spec(tmp_path, NO_MEASURES), frames={})
    assert model.subjects[0].facts == []
    assert {d.entity for d in model.subjects[0].dimensions} == {"customer", "region"}


def test_entity_outside_every_build_is_reported(tmp_path):
    """En entitet som inget bygge nämner får inte försvinna tyst."""
    model = derive_subjects(_spec(tmp_path, UNASSIGNED), frames={})
    assert [u.entity for u in model.unassigned] == ["lonely"]
    assert "lonely" in model.unassigned[0].reason


def test_without_builds_subjects_come_from_graph_components(tmp_path):
    """Utan byggen härleds områden ur entitetsgrafen, så vyn fungerar ändå."""
    model = derive_subjects(_spec(tmp_path, NO_BUILDS), frames={})
    assert len(model.subjects) == 1
    assert {f.entity for f in model.subjects[0].facts} == {"order"}
    assert {d.entity for d in model.subjects[0].dimensions} == {"customer"}


def test_derivation_is_deterministic(tmp_path):
    """Samma spec ska ge samma resultat, varje gång."""
    spec = _spec(tmp_path, TWO_FACTS)
    first = subject_model_to_dict(derive_subjects(spec, frames={}))
    second = subject_model_to_dict(derive_subjects(spec, frames={}))
    assert first == second


def test_derivation_writes_nothing(tmp_path):
    """Härledningen är en vy. Den får inte röra specen."""
    path = tmp_path / "r.yaml"
    path.write_text(TWO_ENTITIES, encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    derive_subjects(load_relation_spec(path), frames={})
    assert path.read_text(encoding="utf-8") == before


def test_frames_are_read_and_real_types_win(tmp_path):
    """Verkliga värden avgör slaget, inte bara deklarerade typer.

    Specen deklarerar ingen typ för ``amount``. Utan filen skulle kolumnen inte
    gå att klassas, och order skulle bli en dimension. När filen läses syns att
    kolumnen är numerisk, och då blir den ett mått.
    """
    _write(
        tmp_path / "o.xlsx",
        "S",
        pd.DataFrame({"order_id": [1, 2], "customer_id": [1, 2], "amount": [10.0, 20.0]}),
    )
    _write(
        tmp_path / "c.xlsx",
        "S",
        pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"]}),
    )
    spec = load_relation_spec(_write_spec(tmp_path, TWO_ENTITIES_UNTYPED))

    without_frames = derive_subjects(spec, frames={})
    assert without_frames.subjects[0].facts == [], "utan fil ska order inte bli fakta"

    with_frames = derive_subjects(spec, frames=load_frames(spec))
    measures = with_frames.subjects[0].measures
    assert [m.column for m in measures] == ["order_amount"]
    assert measures[0].kind == "numeric"


def test_unreadable_source_does_not_crash_derivation(tmp_path):
    """En trasig fil ska inte krascha vyn. Den rapporteras av watch.

    Källan finns men går inte att läsa, så den bidrar inte med några värden.
    Utan deklarerad typ blir order då en dimension i stället för fakta - det är
    rätt, för vi kan inte veta att kolumnen är ett mått. Poängen är att körningen
    fullföljer och att de andra entiteterna klassas som vanligt.
    """
    (tmp_path / "o.xlsx").write_bytes(b"inte en excel-fil")
    _write(
        tmp_path / "c.xlsx",
        "S",
        pd.DataFrame({"customer_id": [1, 2], "name": ["A", "B"], "segment": ["X", "Y"]}),
    )
    spec = load_relation_spec(_write_spec(tmp_path, TWO_ENTITIES_UNTYPED))
    model = derive_subjects(spec, frames=load_frames(spec))

    subject = model.subjects[0]
    assert [d.entity for d in subject.dimensions] == ["customer", "order"]
    assert subject.facts == []
    # Den läsbara källan klassas ändå.
    customer = next(d for d in subject.dimensions if d.entity == "customer")
    assert "customer_name" in customer.attributes


def test_json_form_has_all_sections(tmp_path):
    model = derive_subjects(_spec(tmp_path, TWO_FACTS), frames={})
    payload = subject_model_to_dict(model)
    assert set(payload) == {"subjects", "conformed", "unassigned"}
    assert payload["conformed"][0]["entity"] == "customer"


def _write_spec(tmp_path: Path, text: str) -> Path:
    """Skriv specen med sökvägar som pekar på tmp_path.

    Specens sökvägar tolkas relativt specens katalog, så fixturerna hamnar
    bredvid YAML-filen.
    """
    path = tmp_path / "spec.yaml"
    path.write_text(text, encoding="utf-8")
    return path
