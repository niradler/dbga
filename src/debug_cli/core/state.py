from __future__ import annotations

import json
from pathlib import Path

STATE_DIR_NAME = ".debug-cli"


def state_dir(cwd: Path) -> Path:
    return cwd / STATE_DIR_NAME


def ensure_state_dir(cwd: Path) -> Path:
    d = state_dir(cwd)
    (d / "sessions").mkdir(parents=True, exist_ok=True)
    (d / "snapshots").mkdir(parents=True, exist_ok=True)
    bps = d / "breakpoints.json"
    if not bps.exists():
        bps.write_text("[]", encoding="utf-8")
    inst = d / "instrumentation.json"
    if not inst.exists():
        inst.write_text("{}", encoding="utf-8")
    return d


def read_json(path: Path, *, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
