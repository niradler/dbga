from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

STATE_DIR_NAME = ".debug-cli"


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
