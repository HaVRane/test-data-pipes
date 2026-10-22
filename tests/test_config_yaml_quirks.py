"""Regressionstest för YAML-fallgropen att 'on:' tolkas som boolean True."""

from __future__ import annotations

from excel_merge.config import load_config


def test_bare_on_key_is_read_as_join_key(tmp_path):
    config = tmp_path / "c.yaml"
    config.write_text(
        """\
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
""",
        encoding="utf-8",
    )
    assert load_config(config).join.on == ["id"]
