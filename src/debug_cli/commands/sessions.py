"""CLI surface for the plural ``debug-cli sessions`` (list / cleanup).

Distinct from the singular ``session`` command set, which targets a single
named daemon. ``sessions ls`` scans ``.debug-cli/sessions/`` and:

* reports each daemon that is still alive
* removes any session directory whose pid is dead (zombies)
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from debug_cli.core.format import emit_payload
from debug_cli.core.state import is_pid_alive, state_dir


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("sessions", help="List and clean up debug sessions.")
    sub = p.add_subparsers(dest="sessions_cmd", required=True)

    p_ls = sub.add_parser("ls", help="List active sessions and clean up zombies.")
    p_ls.add_argument("--cwd", help="Working directory for state (default: current directory).")
    p_ls.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    p_ls.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    p_ls.set_defaults(func=cmd_ls)


def _resolve_cwd(args: argparse.Namespace) -> Path:
    return Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()


def _read_meta(meta_path: Path) -> dict[str, Any] | None:
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _summarize(meta: dict[str, Any]) -> dict[str, Any]:
    """Pick the fields useful for ``sessions ls`` output."""
    return {
        "name": meta.get("session_id"),
        "pid": meta.get("pid"),
        "script": meta.get("script"),
        "started_at": meta.get("started_at"),
        "status": meta.get("status"),
        "control_port": meta.get("control_port"),
        "idle_timeout_seconds": meta.get("idle_timeout_seconds"),
    }


def cmd_ls(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    sessions_root = state_dir(cwd) / "sessions"
    payload: dict[str, Any] = {"sessions": [], "cleaned": []}
    if not sessions_root.exists():
        emit_payload(payload, text=args.text, pretty=args.pretty)
        return 0

    active: list[dict[str, Any]] = []
    cleaned: list[dict[str, Any]] = []
    for entry in sorted(sessions_root.iterdir()):
        if not entry.is_dir():
            continue
        meta = _read_meta(entry / "meta.json")
        if meta is None:
            # Could be: directory still being populated, or meta corrupt.
            # Don't touch it — the next start/release will reconcile.
            continue
        pid = meta.get("pid")
        if not isinstance(pid, int):
            # Still spawning — meta.json exists but pid not written yet.
            continue
        if is_pid_alive(pid):
            active.append(_summarize(meta))
            continue
        # Dead pid — zombie directory. Remove it.
        shutil.rmtree(entry, ignore_errors=True)
        cleaned.append({"name": meta.get("session_id") or entry.name, "removed_zombie": True})

    payload["sessions"] = active
    payload["cleaned"] = cleaned
    emit_payload(payload, text=args.text, pretty=args.pretty)
    return 0
