from __future__ import annotations

import argparse
import sys
import traceback

from debug_cli.commands import instrument as instrument_cmd
from debug_cli.commands import localize as localize_cmd
from debug_cli.commands import run as run_cmd
from debug_cli.commands import session as session_cmd
from debug_cli.commands import sessions as sessions_cmd
from debug_cli.commands import watch as watch_cmd
from debug_cli.core.format import emit_error, emit_payload


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
    instrument_cmd.add_subparser(subparsers)
    session_cmd.add_subparser(subparsers)
    sessions_cmd.add_subparser(subparsers)
    return parser


def _emit_flags(args: argparse.Namespace) -> tuple[bool, bool]:
    """Pick out --text/--pretty flags if the parsed command exposes them."""
    return bool(getattr(args, "text", False)), bool(getattr(args, "pretty", False))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    text, pretty = _emit_flags(args)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        emit_payload({"status": "interrupted"}, text=text, pretty=pretty)
        return 130
    except OSError as exc:
        # FileNotFoundError / PermissionError are OSError subclasses.
        return emit_error("io_error", str(exc), text=text, pretty=pretty)
    except Exception as exc:  # noqa: BLE001 — last-resort safety net
        return emit_error(
            "internal",
            f"{type(exc).__name__}: {exc}",
            details={"traceback": traceback.format_exc()},
            text=text,
            pretty=pretty,
        )
