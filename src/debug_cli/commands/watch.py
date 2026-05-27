from __future__ import annotations

import argparse
import os
import shlex
import time
from dataclasses import asdict
from pathlib import Path

from debug_cli.core.format import emit_error, emit_payload
from debug_cli.core.watch import scan_file, scan_process


def _split_cmd(cmd: str) -> list[str]:
    """Cross-platform shell-style split.

    POSIX-mode shlex on Windows mangles backslash path separators. On Windows we
    parse non-POSIX (which preserves backslashes) and then strip surrounding
    matching quotes from each token to get the Popen-ready argv.
    """
    if os.name == "nt":
        tokens = shlex.split(cmd, posix=False)
        return [
            t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'") else t for t in tokens
        ]
    return shlex.split(cmd)


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "watch",
        help="Watch a file or process for regex patterns, return structured matches.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="Path to a file to scan once.")
    src.add_argument("--cmd", help="Shell-style command string to run and tail.")
    p.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="Regex pattern to match. Repeat for multiple.",
    )
    p.add_argument("--until", type=int, default=None, help="Stop after N matches (cmd mode).")
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Wall-clock timeout in seconds for cmd mode (ignored for --file).",
    )
    p.add_argument("--context-lines", type=int, default=1)
    p.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    p.set_defaults(func=cmd_watch)


def cmd_watch(args: argparse.Namespace) -> int:
    patterns: list[str] = args.pattern
    context_lines: int = args.context_lines

    timed_out = False
    try:
        if args.file is not None:
            matches = list(
                scan_file(Path(args.file), patterns=patterns, context_lines=context_lines)
            )
        else:
            cmd_parts = _split_cmd(args.cmd)
            start = time.monotonic()
            matches = list(
                scan_process(
                    cmd_parts,
                    patterns=patterns,
                    timeout=args.timeout,
                    until=args.until,
                    context_lines=context_lines,
                )
            )
            # Only flag timed_out when --until didn't short-circuit; otherwise
            # an elapsed time near ``timeout`` would be misreported.
            until_satisfied = args.until is not None and len(matches) >= args.until
            timed_out = not until_satisfied and (time.monotonic() - start) >= args.timeout
    except OSError as exc:
        return emit_error("io_error", str(exc), text=args.text, pretty=args.pretty)

    payload = {
        "matches": [asdict(m) for m in matches],
        "timed_out": timed_out,
    }
    emit_payload(payload, text=args.text, pretty=args.pretty)
    return 0
