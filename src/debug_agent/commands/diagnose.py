"""``dbga diagnose`` — one-call crash localization.

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

from debug_agent.adapters import get_adapter, list_adapters, resolve_language
from debug_agent.commands.session import start_session_inline
from debug_agent.core.format import emit_error, emit_payload
from debug_agent.core.process import run_with_timeout
from debug_agent.core.tracebacks import ParsedTraceback, attach_source


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
    p.add_argument(
        "--lang",
        choices=list_adapters(),
        default=None,
        help=(
            "Language adapter for traceback parsing and rerun. Defaults to "
            "auto-detection from the command (e.g. 'python foo.py' → python)."
        ),
    )
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


def _infer_lang_from_cmd(cmd: list[str]) -> str | None:
    """Best-effort language inference from a command line.

    Looks first for a known interpreter in ``cmd[0]`` (``python foo.py`` →
    python). If that fails, falls back to extension detection on the first
    argument that has a recognised file suffix.
    """
    from debug_agent.adapters import _REGISTRY, detect_language

    if not cmd:
        return None
    base = Path(cmd[0]).name.lower()
    stripped = base.removesuffix(".exe")
    for name, cls in _REGISTRY.items():
        if base in cls.interpreter_basenames or stripped in cls.interpreter_basenames:
            return name
    for arg in cmd:
        if not arg.startswith("-"):
            detected = detect_language(arg)
            if detected is not None:
                return detected
    return None


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

    # Resolve the language adapter so traceback parsing and launch-target
    # detection both speak the same dialect.
    try:
        lang = resolve_language(
            explicit=getattr(args, "lang", None),
            script=None,
            default=_infer_lang_from_cmd(cmd) or "python",
        )
    except ValueError as exc:
        return emit_error("usage", str(exc), text=args.text, pretty=args.pretty)
    adapter = get_adapter(lang)

    result = run_with_timeout(cmd, timeout=float(args.timeout), cwd=cwd)
    combined = (result.stdout or "") + (result.stderr or "")
    parsed = adapter.parse_traceback(combined)
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

    return _rerun_under_session(args, cmd, cwd, parsed, lang=lang)


def _rerun_under_session(
    args: argparse.Namespace,
    cmd: list[str],
    cwd: Path,
    parsed: ParsedTraceback,
    *,
    lang: str,
) -> int:
    assert parsed.deepest_user_frame is not None  # checked by caller
    frame = parsed.deepest_user_frame
    bp_file = Path(frame.file)
    bp_file = (cwd / bp_file).resolve() if not bp_file.is_absolute() else bp_file.resolve()

    # The adapter knows how to peel its interpreter (``python foo.py`` →
    # ``foo.py``). For commands that aren't an interpreter invocation it
    # returns ``cmd[0]`` as the launchable program (``pytest``, ``./manage.py``).
    adapter = get_adapter(lang)
    target = adapter.resolve_launch_target(cmd)
    if target is None:
        payload = {
            "status": "crash",
            "traceback": asdict(parsed),
            "note": f"cannot rerun: no launchable script inferred from cmd for {lang!r}",
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
        lang=lang,
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
