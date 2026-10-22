"""Tester för konfigurationsvalidering - snabba, ingen Excel inblandad."""

from __future__ import annotations

import pytest

from excel_merge.config import ConfigError, load_config

VALID = """\
sources:
  - name: a
    path: a.xlsx
    sheet: S
    columns: {id: id}
  - name: b
    path: b.xlsx
    sheet: S
    columns: {id: id}
join:
  on: [id]
output:
  path: out.xlsx
  sheet: Out
"""


def _write(tmp_path, text: str):
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_config(tmp_path):
    config = load_config(_write(tmp_path, VALID))
    assert [s.name for s in config.sources] == ["a", "b"]
    assert config.join.how == "left"
    assert config.version == 1


def test_rejects_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="hittades inte"):
        load_config(tmp_path / "nope.yaml")


def test_rejects_single_source(tmp_path):
    one = VALID.replace(
        "  - name: b\n    path: b.xlsx\n    sheet: S\n    columns: {id: id}\n", ""
    )
    with pytest.raises(ConfigError, match="minst två källor"):
        load_config(_write(tmp_path, one))


def test_rejects_duplicate_source_names(tmp_path):
    dup = VALID.replace("name: b", "name: a")
    with pytest.raises(ConfigError, match="unika"):
        load_config(_write(tmp_path, dup))


def test_rejects_unknown_join_key(tmp_path):
    bad = VALID.replace("on: [id]", "on: [saknas]")
    with pytest.raises(ConfigError, match="nyckelkolumn"):
        load_config(_write(tmp_path, bad))


def test_rejects_bad_join_how(tmp_path):
    bad = VALID.replace("join:\n", "join:\n  how: sideways\n").replace("  on: [id]", "  on: [id]")
    with pytest.raises(ConfigError, match="join.how"):
        load_config(_write(tmp_path, bad))


def test_rejects_unknown_output_column(tmp_path):
    bad = VALID + "  columns: [id, fantomkolumn]\n"
    with pytest.raises(ConfigError, match="produceras"):
        load_config(_write(tmp_path, bad))


def test_rejects_dtype_for_unknown_column(tmp_path):
    bad = VALID.replace(
        "    columns: {id: id}\n  - name: b",
        "    columns: {id: id}\n    dtypes: {fel: int}\n  - name: b",
    )
    with pytest.raises(ConfigError, match="dtypes"):
        load_config(_write(tmp_path, bad))
