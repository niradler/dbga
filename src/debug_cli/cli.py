from __future__ import annotations

import argparse
import sys

from debug_cli.commands import localize as localize_cmd
from debug_cli.commands import run as run_cmd
from debug_cli.commands import watch as watch_cmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="debug-cli",
        description="Evidence-first Python debugger CLI for AI agents.",
    )
    parser.add_argument("--version", action="version", version="0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_cmd.add_subparser(subparsers)
    watch_cmd.add_subparser(subparsers)
    localize_cmd.add_subparser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args))
