from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from debug_cli.core.format import emit_error as _emit_error_payload
from debug_cli.core.format import emit_payload
from debug_cli.core.instrumentation import (
    VALID_KINDS,
    add_instrumentation,
    list_instrumentations,
    revert,
)


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cwd", help="Working directory for state (default: current directory).")
    p.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "instrument",
        help="Inject reversible probes into source code at file:line.",
    )
    sub = p.add_subparsers(dest="instrument_cmd", required=True)

    p_add = sub.add_parser("add", help="Insert an instrumentation probe at file:line.")
    p_add.add_argument("target", help="Target location as <file>:<line>.")
    p_add.add_argument("--code", required=True, help="Code snippet to insert.")
    p_add.add_argument(
        "--kind",
        required=True,
        choices=sorted(VALID_KINDS),
        help="Kind of instrumentation.",
    )
    p_add.add_argument(
        "--allow-outside",
        action="store_true",
        help="Allow targets outside --cwd.",
    )
    _add_common_flags(p_add)
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List all recorded instrumentations.")
    _add_common_flags(p_list)
    p_list.set_defaults(func=cmd_list)

    p_rev = sub.add_parser("revert", help="Revert instrumentation(s).")
    group = p_rev.add_mutually_exclusive_group(required=True)
    group.add_argument("inst_id", nargs="?", help="Instrumentation id to revert.")
    group.add_argument("--all", action="store_true", help="Revert all instrumentations.")
    _add_common_flags(p_rev)
    p_rev.set_defaults(func=cmd_revert)


def _resolve_cwd(args: argparse.Namespace) -> Path:
    return Path(args.cwd) if args.cwd else Path.cwd()


def _emit(args: argparse.Namespace, payload: dict[str, object]) -> None:
    emit_payload(payload, text=args.text, pretty=args.pretty)


def _emit_error(args: argparse.Namespace, message: str, *, error_type: str = "usage") -> None:
    _emit_error_payload(error_type, message, text=args.text, pretty=args.pretty)


def _parse_target(target: str) -> tuple[Path, int] | None:
    sep = target.rfind(":")
    if sep <= 0:
        return None
    file_part, line_part = target[:sep], target[sep + 1 :]
    try:
        line = int(line_part)
    except ValueError:
        return None
    if line < 1:
        return None
    return Path(file_part), line


def cmd_add(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    parsed = _parse_target(args.target)
    if parsed is None:
        _emit_error(args, f"invalid target {args.target!r}; expected <file>:<line>")
        return 2
    file, line = parsed

    if not args.allow_outside:
        try:
            resolved = file.resolve()
            cwd_resolved = cwd.resolve()
        except OSError as exc:
            _emit_error(args, f"failed to resolve path: {exc}")
            return 2
        if not resolved.is_relative_to(cwd_resolved):
            _emit_error(
                args,
                f"file {file} is outside cwd {cwd}; pass --allow-outside to override",
                error_type="safety",
            )
            return 2

    if not file.exists():
        _emit_error(args, f"file not found: {file}", error_type="not_found")
        return 2

    try:
        inst_id = add_instrumentation(file, line=line, code=args.code, kind=args.kind, cwd=cwd)
    except ValueError as exc:
        _emit_error(args, str(exc))
        return 2

    _emit(
        args,
        {"id": inst_id, "file": str(file), "line": line, "kind": args.kind},
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    entries = list_instrumentations(cwd=cwd)
    _emit(args, {"instrumentations": [asdict(e) for e in entries]})
    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    inst_id: str | None = None if args.all else args.inst_id
    try:
        reverted = revert(inst_id, cwd=cwd)
    except KeyError as exc:
        _emit_error(args, str(exc).strip("'"), error_type="not_found")
        return 2
    _emit(args, {"reverted": reverted})
    return 0
