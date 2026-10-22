"""Indatarelationerna: datakällorna och nycklarna som binder dem samman."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from webapp import build_relationship_map  # noqa: E402


def _write(path: Path, sheet: str, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, index=False, sheet_name=sheet)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    inbox = data / "inbox"
    inbox.mkdir(parents=True)
    _write(
        data / "kunder.xlsx",
        "Kunder",
        pd.DataFrame({"kund_id": [1, 2, 3], "namn": ["Anna", "Bo", "Cissi"]}),
    )
    _write(
        data / "ordrar.xlsx",
        "Ordrar",
        pd.DataFrame({"order_id": [10, 11, 12], "kund_id": [1, 2, 3], "belopp": [100, 200, 300]}),
    )
    return data


def test_nodes_describe_each_sheet(data_dir):
    result = build_relationship_map(data_dir, data_dir / "inbox")
    ids = sorted(n["id"] for n in result["nodes"])
    assert ids == ["kunder/Kunder", "ordrar/Ordrar"]


def test_node_carries_rows_and_column_count(data_dir):
    result = build_relationship_map(data_dir, data_dir / "inbox")
    node = next(n for n in result["nodes"] if n["id"] == "kunder/Kunder")
    assert node["rows"] == 3
    assert node["column_count"] == 2
    assert node["file"] == "data/kunder.xlsx"
    assert node["sheet"] == "Kunder"


def test_node_lists_candidate_keys_only(data_dir):
    """Relationerna ska visa möjliga nycklar, inte alla kolumner."""
    result = build_relationship_map(data_dir, data_dir / "inbox")
    node = next(n for n in result["nodes"] if n["id"] == "kunder/Kunder")
    assert "kund_id" in node["candidate_keys"]
    # Antal kolumner redovisas som siffra, inte som lista.
    assert "columns" not in node


def test_shared_key_becomes_a_recommended_edge(data_dir):
    result = build_relationship_map(data_dir, data_dir / "inbox")
    edges = [e for e in result["edges"] if {e["left"], e["right"]} == {"kunder/Kunder", "ordrar/Ordrar"}]
    assert edges, "kund_id borde ge en koppling"
    best = edges[0]
    assert best["verdict"] == "rekommenderad"
    assert {best["left_column"], best["right_column"]} == {"kund_id"}


def test_edge_reports_coverage_and_cardinality(data_dir):
    result = build_relationship_map(data_dir, data_dir / "inbox")
    edge = result["edges"][0]
    assert edge["coverage"] == 1.0
    assert edge["cardinality"]


def test_unrelated_sheet_is_marked_isolated(data_dir):
    _write(
        data_dir / "ovrigt.xlsx",
        "Ovrigt",
        pd.DataFrame({"text": ["a", "b"], "siffra": [1, 2]}),
    )
    result = build_relationship_map(data_dir, data_dir / "inbox")
    node = next(n for n in result["nodes"] if n["id"] == "ovrigt/Ovrigt")
    assert node["isolated"] is True


def test_connected_sheets_are_not_isolated(data_dir):
    result = build_relationship_map(data_dir, data_dir / "inbox")
    for node in result["nodes"]:
        assert node["isolated"] is False


def test_map_limits_edges_per_pair(tmp_path):
    """En tabell med många liknande kolumner ska inte fylla relationerna med kanter."""
    data = tmp_path / "data"
    inbox = data / "inbox"
    inbox.mkdir(parents=True)
    _write(data / "a.xlsx", "A", pd.DataFrame({"k": [1, 2, 3], "x": [1, 2, 3]}))
    _write(data / "b.xlsx", "B", pd.DataFrame({"k": [1, 2, 3], "x": [1, 2, 3]}))
    result = build_relationship_map(data, inbox, max_edges_per_pair=1)
    assert len(result["edges"]) == 1


def test_empty_directory_gives_empty_map(tmp_path):
    data = tmp_path / "data"
    (data / "inbox").mkdir(parents=True)
    result = build_relationship_map(data, data / "inbox")
    assert result == {"nodes": [], "edges": []}


def test_broken_file_does_not_crash_the_map(data_dir):
    (data_dir / "trasig.xlsx").write_bytes(b"inte ett kalkylark")
    result = build_relationship_map(data_dir, data_dir / "inbox")
    assert any(n["id"] == "kunder/Kunder" for n in result["nodes"])


def test_map_is_json_serialisable(data_dir):
    result = build_relationship_map(data_dir, data_dir / "inbox")
    assert json.loads(json.dumps(result))["nodes"]


def test_key_used_in_a_join_is_listed_even_if_not_unique(tmp_path):
    """En kolumn som en pil pekar på ska visas som nyckel, annars motsäger de sig."""
    data = tmp_path / "data"
    inbox = data / "inbox"
    inbox.mkdir(parents=True)
    # grupp_id är inte unikt i höger tabell (många rader per grupp).
    _write(data / "grupper.xlsx", "Grupper", pd.DataFrame({"grupp_id": [1, 2], "namn": ["A", "B"]}))
    _write(data / "rader.xlsx", "Rader", pd.DataFrame({"grupp_id": [1, 1, 2], "varde": [5, 6, 7]}))
    result = build_relationship_map(data, inbox)
    node = next(n for n in result["nodes"] if n["id"] == "rader/Rader")
    assert "grupp_id" in node["candidate_keys"]


def test_no_duplicate_keys_in_a_node(tmp_path):
    data = tmp_path / "data"
    inbox = data / "inbox"
    inbox.mkdir(parents=True)
    _write(data / "a.xlsx", "A", pd.DataFrame({"id": [1, 2], "namn": ["x", "y"]}))
    _write(data / "b.xlsx", "B", pd.DataFrame({"id": [1, 2], "v": [3, 4]}))
    result = build_relationship_map(data, inbox)
    for node in result["nodes"]:
        assert len(node["candidate_keys"]) == len(set(node["candidate_keys"]))


def test_measure_and_date_columns_are_not_listed_as_keys(tmp_path):
    """Ett belopp eller datum blir unikt av en slump i små data - inte en nyckel."""
    data = tmp_path / "data"
    inbox = data / "inbox"
    inbox.mkdir(parents=True)
    _write(
        data / "ordrar.xlsx",
        "Ordrar",
        pd.DataFrame({
            "order_id": [10, 11, 12],
            "belopp": [100, 200, 300],
            "order_date": ["2024-01-01", "2024-02-01", "2024-03-01"],
        }),
    )
    result = build_relationship_map(data, inbox)
    node = result["nodes"][0]
    assert "order_id" in node["candidate_keys"]
    assert "belopp" not in node["candidate_keys"]
    assert "order_date" not in node["candidate_keys"]
