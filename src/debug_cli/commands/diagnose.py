"""``debug-cli diagnose`` — one-call crash localization.

Runs an arbitrary command under a timeout, parses any Python traceback it
emits, and (by default) re-runs it under a debug session paused at the
deepest user frame. This is the workflow's killer move: from "my command
crashes" to "a live, stopped debugger at the failure point" in one step.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

from debug_cli.commands.session import start_session_inline
from debug_cli.core.format import emit_error, emit_payload
from debug_cli.core.process import run_with_timeout
from debug_cli.core.tracebacks import (
    ParsedTraceback,
    attach_source,
    parse_traceback,
)


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "diagnose",
        help="Run a command, parse its traceback, open a session paused at the failure.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the command (default 30).",
    )
    rerun = p.add_mutually_exclusive_group()
    rerun.add_argument(
        "--rerun",
        dest="rerun",
        action="store_true",
        help="On crash, re-run under a session paused at the deepest user frame (default).",
    )
    rerun.add_argument(
        "--no-rerun",
        dest="rerun",
        action="store_false",
        help="Report the parsed traceback without spawning a session.",
    )
    p.set_defaults(rerun=True)
    p.add_argument("--session", default="default", help="Session name to use for rerun.")
    p.add_argument("--cwd", help="Working directory for the command and state.")
    p.add_argument("--text", action="store_true", help="Human-readable output.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    p.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command (and args) to run. Prefix with ``--`` to disambiguate flags.",
    )
    p.set_defaults(func=cmd_diagnose)


def _strip_leading_dashdash(cmd: list[str]) -> list[str]:
    """argparse keeps a leading ``--`` in REMAINDER; drop it for a clean argv."""
    return cmd[1:] if cmd and cmd[0] == "--" else list(cmd)


_PYTHON_BASENAMES = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}


def _is_python_interpreter(arg: str) -> bool:
    """True if ``arg`` looks like a python interpreter the user invoked the script with."""
    base = Path(arg).name.lower()
    return base in _PYTHON_BASENAMES


def _resolve_launch_target(cmd: list[str]) -> tuple[str, list[str]] | None:
    """Pick the script + args debugpy should launch given the user's command.

    For ``python foo.py a b`` we strip the interpreter and launch ``foo.py``
    with ``[a, b]``. For anything else we trust cmd[0] is the launchable
    program (e.g. ``pytest``, ``./manage.py``). Returns ``None`` when we
    can't infer a launchable script (e.g. ``python -m module``) — the
    caller should fall back to ``--no-rerun`` behavior.
    """
    if len(cmd) >= 2 and _is_python_interpreter(cmd[0]):
        # If the user invoked the interpreter with ``-m`` / ``-c``, there's
        # no script path we can hand to debugpy as ``program``. Bail out and
        # let the caller report the crash without rerunning.
        if any(flag in cmd[1:] for flag in ("-m", "-c")):
            return None
        # Skip other interpreter flags (``-O``, ``-X``, ``-W``) and use the
        # first non-flag argument as the script.
        i = 1
        while i < len(cmd) and cmd[i].startswith("-"):
            i += 1
        if i < len(cmd):
            return cmd[i], list(cmd[i + 1 :])
    return cmd[0], list(cmd[1:])


def cmd_diagnose(args: argparse.Namespace) -> int:
    cmd = _strip_leading_dashdash(list(args.cmd or []))
    if not cmd:
        return emit_error(
            "usage",
            "diagnose requires a command after '--'",
            text=args.text,
            pretty=args.pretty,
        )

    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()
    result = run_with_timeout(cmd, timeout=float(args.timeout), cwd=cwd)
    combined = (result.stdout or "") + (result.stderr or "")
    parsed = parse_traceback(combined)
    attach_source(parsed, cwd=cwd)

    if parsed.deepest_user_frame is None:
        # Either the command succeeded or it failed without producing a parseable traceback.
        payload: dict[str, Any] = {
            "status": "no_crash",
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        emit_payload(payload, text=args.text, pretty=args.pretty)
        return 0 if result.exit_code == 0 else 1

    if not args.rerun:
        payload = {
            "status": "crash",
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "traceback": asdict(parsed),
        }
        emit_payload(payload, text=args.text, pretty=args.pretty)
        return 1

    return _rerun_under_session(args, cmd, cwd, parsed)


def _rerun_under_session(
    args: argparse.Namespace,
    cmd: list[str],
    cwd: Path,
    parsed: ParsedTraceback,
) -> int:
    assert parsed.deepest_user_frame is not None  # checked by caller
    frame = parsed.deepest_user_frame
    bp_file = Path(frame.file)
    bp_file = (cwd / bp_file).resolve() if not bp_file.is_absolute() else bp_file.resolve()

    # If the user wrote ``python <script> args...`` we want to debug the
    # script (which is what debugpy launches), not the interpreter binary.
    # For other commands (e.g. ``pytest tests/``) the entry point IS a Python
    # script on PATH that debugpy can launch directly.
    target = _resolve_launch_target(cmd)
    if target is None:
        # ``python -m foo`` / ``-c``: we have a real crash but no script
        # path to rerun under debugpy. Surface the crash and let the caller
        # rerun manually with an explicit script.
        payload = {
            "status": "crash",
            "traceback": asdict(parsed),
            "note": "cannot rerun: 'python -m'/'python -c' invocations are unsupported",
        }
        emit_payload(payload, text=args.text, pretty=args.pretty)
        return 1
    script, script_args = target
    breakpoints = [{"file": str(bp_file), "line": frame.line, "condition": None}]

    start_result = start_session_inline(
        cwd=cwd,
        session_name=args.session,
        script=script,
        script_args=script_args,
        breakpoints=breakpoints,
        stop_on_entry=False,
    )
    if start_result["status"] == "error":
        # Emit the structured error directly so the caller sees what blew up.
        return emit_error(
            start_result.get("error_type", "daemon_failed"),
            start_result["message"],
            text=args.text,
            pretty=args.pretty,
        )
    payload = {
        "status": "diagnosed",
        "traceback": asdict(parsed),
        "session_context": start_result["payload"],
    }
    emit_payload(payload, text=args.text, pretty=args.pretty)
    return 0
