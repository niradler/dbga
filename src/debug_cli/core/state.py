from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

STATE_DIR_NAME = ".debug-cli"
BREAKPOINTS_FILE = "breakpoints.json"


def state_dir(cwd: Path) -> Path:
    return cwd / STATE_DIR_NAME


def session_dir(cwd: Path, name: str) -> Path:
    return state_dir(cwd) / "sessions" / name


def is_pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` is currently running.

    Best-effort, cross-platform. On Windows we shell out to ``tasklist`` so we
    don't have to depend on ``psutil``; on POSIX we use ``os.kill(pid, 0)``
    which only signals the process for existence checking.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        # tasklist prints a header even on no-match; the PID only appears in
        # the body when alive. Match against the PID with whitespace around.
        return f" {pid} " in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it — still alive.
        return True
    except OSError:
        return False
    return True


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


# ---- shared breakpoints file -------------------------------------------------


def _breakpoints_path(cwd: Path) -> Path:
    return state_dir(cwd) / BREAKPOINTS_FILE


def _normalize_bp(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce a raw json entry into our canonical shape, or ``None`` if invalid."""
    file = entry.get("file")
    line = entry.get("line")
    if not isinstance(file, str) or not isinstance(line, int) or line < 1:
        return None
    cond = entry.get("condition")
    return {
        "file": file,
        "line": int(line),
        "condition": cond if isinstance(cond, str) else None,
    }


def read_breakpoints(cwd: Path) -> list[dict[str, Any]]:
    """Read ``.debug-cli/breakpoints.json``. Missing/invalid entries are skipped."""
    raw = read_json(_breakpoints_path(cwd), default=[])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, dict):
            norm = _normalize_bp(entry)
            if norm is not None:
                out.append(norm)
    return out


def write_breakpoints(cwd: Path, bps: list[dict[str, Any]]) -> None:
    """Write the shared breakpoints file. Caller owns the full content."""
    path = _breakpoints_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, bps)


def merge_breakpoints(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union by ``(file, line)`` — later condition wins, preserves first-seen order."""
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    order: list[tuple[str, int]] = []
    for entry in (*existing, *new):
        norm = _normalize_bp(entry)
        if norm is None:
            continue
        key = (norm["file"], norm["line"])
        if key not in by_key:
            order.append(key)
        by_key[key] = norm
    return [by_key[k] for k in order]


def remove_breakpoint(existing: list[dict[str, Any]], file: str, line: int) -> list[dict[str, Any]]:
    """Return a new list with the matching ``(file, line)`` removed."""
    return [
        entry for entry in existing if not (entry.get("file") == file and entry.get("line") == line)
    ]
