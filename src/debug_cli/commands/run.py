from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from debug_cli.core.format import format_json, format_text
from debug_cli.core.process import run_with_timeout


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
        error = {"status": "error", "error_type": "usage", "message": "no command provided"}
        print(format_json(error))
        return 1
    cwd = Path(args.cwd) if args.cwd else None
    result = run_with_timeout(cmd, timeout=args.timeout, cwd=cwd)
    payload = asdict(result)
    if args.text:
        print(format_text(payload))
    else:
        print(format_json(payload, pretty=args.pretty))
    return 0
