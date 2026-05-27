from __future__ import annotations

import json
from pathlib import Path

from debug_cli.core.state import ensure_state_dir, read_json, state_dir, write_json


def test_ensure_state_dir_creates_structure(tmp_path: Path) -> None:
    d = ensure_state_dir(tmp_path)
    assert d == tmp_path / ".debug-cli"
    assert (d / "sessions").is_dir()
    assert (d / "snapshots").is_dir()
    assert json.loads((d / "breakpoints.json").read_text()) == []
    assert json.loads((d / "instrumentation.json").read_text()) == {}


def test_read_json_returns_default_when_missing(tmp_path: Path) -> None:
    assert read_json(tmp_path / "missing.json", default={"x": 1}) == {"x": 1}


def test_write_read_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    write_json(p, {"a": [1, 2, 3]})
    assert read_json(p, default=None) == {"a": [1, 2, 3]}


def test_state_dir_returns_path(tmp_path: Path) -> None:
    assert state_dir(tmp_path) == tmp_path / ".debug-cli"
