from __future__ import annotations

import json
from pathlib import Path

from debug_cli.core.state import (
    ensure_state_dir,
    merge_breakpoints,
    read_breakpoints,
    read_json,
    remove_breakpoint,
    state_dir,
    write_breakpoints,
    write_json,
)


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


def test_breakpoints_roundtrip(tmp_path: Path) -> None:
    ensure_state_dir(tmp_path)
    bps = [{"file": "a.py", "line": 5, "condition": None}]
    write_breakpoints(tmp_path, bps)
    assert read_breakpoints(tmp_path) == bps


def test_merge_breakpoints_dedupes_and_keeps_newer_condition() -> None:
    existing = [{"file": "a.py", "line": 5, "condition": None}]
    new = [
        {"file": "a.py", "line": 5, "condition": "x > 0"},
        {"file": "b.py", "line": 1, "condition": None},
    ]
    merged = merge_breakpoints(existing, new)
    assert merged == [
        {"file": "a.py", "line": 5, "condition": "x > 0"},
        {"file": "b.py", "line": 1, "condition": None},
    ]


def test_merge_breakpoints_skips_invalid_entries() -> None:
    merged = merge_breakpoints(
        [{"file": "a.py", "line": 1, "condition": None}],
        [
            {"file": "b.py", "line": 0, "condition": None},  # invalid line
            {"file": 5, "line": 2, "condition": None},  # invalid file type
            {"file": "c.py", "line": 3, "condition": None},  # ok
        ],
    )
    files = [e["file"] for e in merged]
    assert files == ["a.py", "c.py"]


def test_remove_breakpoint() -> None:
    entries = [
        {"file": "a.py", "line": 5, "condition": None},
        {"file": "a.py", "line": 7, "condition": None},
    ]
    assert remove_breakpoint(entries, "a.py", 5) == [{"file": "a.py", "line": 7, "condition": None}]
    # Removing something not present returns the list unchanged.
    assert remove_breakpoint(entries, "a.py", 99) == entries
