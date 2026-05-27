from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from debug_cli.core.format import emit_error, emit_payload
from debug_cli.core.tracebacks import attach_source, parse_traceback


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "localize",
        help="Parse a Python traceback into structured data.",
    )
    p.add_argument("--file", help="Path to a file containing a traceback.")
    p.add_argument("--stdin", action="store_true", help="Read traceback from stdin.")
    p.add_argument("traceback_text", nargs="?", help="Traceback text as a positional argument.")
    p.add_argument(
        "--context-lines",
        type=int,
        default=2,
        help="Number of source lines to include on each side of a frame's line.",
    )
    p.add_argument(
        "--cwd",
        help="Directory for resolving relative frame paths (default: current directory).",
    )
    p.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    p.set_defaults(func=cmd_localize)


def cmd_localize(args: argparse.Namespace) -> int:
    sources = sum(1 for x in (args.file, args.stdin, args.traceback_text) if x)
    if sources != 1:
        return emit_error(
            "usage",
            "exactly one of --file, --stdin, or positional traceback_text is required",
            text=args.text,
            pretty=args.pretty,
        )

    try:
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8")
        elif args.stdin:
            text = sys.stdin.read()
        else:
            text = args.traceback_text or ""
    except OSError as exc:
        return emit_error("io_error", str(exc), text=args.text, pretty=args.pretty)

    parsed = parse_traceback(text)
    cwd = Path(args.cwd) if args.cwd else None
    attach_source(parsed, context_lines=args.context_lines, cwd=cwd)

    emit_payload(asdict(parsed), text=args.text, pretty=args.pretty)
    return 0
