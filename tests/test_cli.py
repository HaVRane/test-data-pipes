"""End-to-end-test av kommandoradsgränssnittet, inklusive felvägar."""

from __future__ import annotations

import pandas as pd
import pytest

from excel_merge.cli import main
from fixtures import build_sample_sources


def test_cli_success(make_config, capsys):
    assert main(["--config", str(make_config())]) == 0
    out = capsys.readouterr().out
    assert "läste customers: 4 rader" in out
    assert "skrev" in out


def test_cli_returns_1_on_broken_config(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sources: []\n", encoding="utf-8")
    assert main(["--config", str(bad)]) == 1
    assert "FEL" in capsys.readouterr().err


def test_cli_reports_missing_source_file(tmp_path, make_config, capsys):
    config = make_config()
    (tmp_path / "customers.xlsx").unlink()
    assert main(["--config", str(config)]) == 1
    assert "hittades inte" in capsys.readouterr().err


@pytest.mark.parametrize("how,expected_rows", [("left", 4), ("inner", 3), ("outer", 5)])
def test_cli_join_modes(make_config, how, expected_rows):
    config = make_config(how=how)
    assert main(["--config", str(config)]) == 0
    written = pd.read_excel(config.parent / "out" / "merged.xlsx", sheet_name="Merged")
    assert len(written) == expected_rows
