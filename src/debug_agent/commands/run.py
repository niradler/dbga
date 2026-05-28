from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from debug_agent.core.format import emit_error, emit_payload
from debug_agent.core.process import run_with_timeout


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("run", help="Run a command with timeout, return structured result.")
    p.add_argument("--timeout", type=float, required=True)
    p.add_argument("--cwd")
    p.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and args after --.")
    p.set_defaults(func=cmd_run)


def cmd_run(args: argparse.Namespace) -> int:
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        return emit_error("usage", "no command provided", text=args.text, pretty=args.pretty)
    cwd = Path(args.cwd) if args.cwd else None
    try:
        result = run_with_timeout(cmd, timeout=args.timeout, cwd=cwd)
    except OSError as exc:
        # ``FileNotFoundError``/``PermissionError`` are OSError subclasses; we
        # collapse them all into ``io_error`` so callers get a single shape.
        return emit_error("io_error", str(exc), text=args.text, pretty=args.pretty)
    emit_payload(asdict(result), text=args.text, pretty=args.pretty)
    return 0
