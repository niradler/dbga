"""CLI surface for ``dbga session start / inspect / release / stop``.

The CLI itself is stateless: it spawns a detached background Python process
(``debug_agent.core.session_proc``) that owns the live ``DapSession``, then
talks to it over a localhost TCP control socket via length-prefixed JSON.

Subsequent commands re-read ``.debug-agent/sessions/<name>/meta.json`` to
locate the control port and dispatch one-shot requests.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from debug_agent.core import control_proto
from debug_agent.core.format import emit_error as _emit_error_payload
from debug_agent.core.format import emit_payload
from debug_agent.core.process import kill_tree, windows_no_window_flags
from debug_agent.core.state import (
    ensure_state_dir,
    is_pid_alive,
    merge_breakpoints,
    read_breakpoints,
    session_dir,
)

_CONTROL_PORT_POLL_INTERVAL = 0.1
_CONTROL_PORT_POLL_TIMEOUT = 15.0
_RELEASE_WAIT_TIMEOUT = 5.0


# ---- parser wiring ----------------------------------------------------------


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cwd", help="Working directory for state (default: current directory).")
    p.add_argument("--session", default="default", help="Session name (default: 'default').")
    p.add_argument("--text", action="store_true", help="Human-readable output instead of JSON.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")


def _add_context_lines_flag(p: argparse.ArgumentParser) -> None:
    """Attach ``--context-lines N`` for commands whose response includes a context."""
    p.add_argument(
        "--context-lines",
        type=int,
        default=None,
        help="Source lines on each side of the stop location (overrides session default).",
    )


def _with_context_lines(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    """Inject ``context_lines`` into a daemon-bound payload if the user set it."""
    if getattr(args, "context_lines", None) is not None:
        payload["context_lines"] = int(args.context_lines)
    return payload


def add_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser(
        "session",
        help="Manage a long-lived background DAP session (start/inspect/release).",
    )
    sub = p.add_subparsers(dest="session_cmd", required=True)

    p_start = sub.add_parser("start", help="Spawn a background debug session and stop at entry.")
    p_start.add_argument(
        "--break-at",
        action="append",
        default=[],
        dest="break_at",
        help="Breakpoint as <file>:<line>[:condition]. Repeatable.",
    )
    p_start.add_argument(
        "--stop-on-entry",
        action="store_true",
        help="Stop on the first line of the script.",
    )
    p_start.add_argument(
        "--idle-timeout",
        type=float,
        default=1800.0,
        help="Seconds of inactivity before the daemon exits (default 1800).",
    )
    p_start.add_argument(
        "--start-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the initial stop event (default 30).",
    )
    p_start.add_argument(
        "--context-lines",
        type=int,
        default=5,
        help="Source lines on each side of the current stop location (default 5).",
    )
    p_start.add_argument(
        "--listen",
        type=int,
        default=None,
        metavar="PORT",
        help=(
            "Spawn the debuggee in debugpy listen mode for VS Code remote-attach. "
            "Returns attach_url; daemon-controlled session features are disabled."
        ),
    )
    p_start.add_argument(
        "--use-bps-file",
        action="store_true",
        help="Merge breakpoints from .debug-agent/breakpoints.json into the initial set.",
    )
    p_start.add_argument(
        "--no-write-bps-file",
        action="store_true",
        help="Don't write back to .debug-agent/breakpoints.json on set-bp/clear-bp.",
    )
    _add_common_flags(p_start)
    p_start.add_argument("script", help="Path to the Python script to debug.")
    p_start.add_argument(
        "script_args",
        nargs="*",
        help="Args passed to the script (no leading-dash args supported in this phase).",
    )
    p_start.set_defaults(func=cmd_start)

    p_inspect = sub.add_parser("inspect", help="Re-read the current stopped state.")
    _add_context_lines_flag(p_inspect)
    _add_common_flags(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect)

    p_release = sub.add_parser("release", help="Tear down the background session.")
    _add_common_flags(p_release)
    p_release.set_defaults(func=cmd_release)

    p_stop = sub.add_parser("stop", help="Alias for 'release'.")
    _add_common_flags(p_stop)
    p_stop.set_defaults(func=cmd_release)

    p_eval = sub.add_parser("eval", help="Evaluate a Python expression in the current frame.")
    p_eval.add_argument("--expr", required=True, help="Expression to evaluate.")
    p_eval.add_argument("--frame", type=int, default=None, help="Frame id (default: current top).")
    _add_context_lines_flag(p_eval)
    _add_common_flags(p_eval)
    p_eval.set_defaults(func=cmd_eval)

    p_continue = sub.add_parser("continue", help="Resume execution until next stop.")
    p_continue.add_argument(
        "--break",
        action="append",
        default=[],
        dest="break_add",
        metavar="FILE:LINE[:COND]",
        help="Add a breakpoint before continuing. Repeatable.",
    )
    p_continue.add_argument(
        "--remove-break",
        action="append",
        default=[],
        dest="break_remove",
        metavar="FILE:LINE",
        help="Remove a breakpoint before continuing. Repeatable.",
    )
    p_continue.add_argument(
        "--to",
        default=None,
        metavar="FILE:LINE",
        help="Temporary breakpoint at this location, removed after stop.",
    )
    p_continue.add_argument(
        "--break-on-exception",
        action="append",
        default=[],
        dest="exc_filters",
        metavar="FILTER",
        help="Exception filter (e.g. 'raised', 'uncaught'). Repeatable.",
    )
    _add_context_lines_flag(p_continue)
    _add_common_flags(p_continue)
    p_continue.set_defaults(func=cmd_continue)

    p_step = sub.add_parser("step", help="Step one source line.")
    p_step.add_argument(
        "--mode",
        choices=("in", "out", "over"),
        default="over",
        help="Step mode (default: over).",
    )
    _add_context_lines_flag(p_step)
    _add_common_flags(p_step)
    p_step.set_defaults(func=cmd_step)

    p_pause = sub.add_parser("pause", help="Interrupt a running debuggee.")
    _add_common_flags(p_pause)
    p_pause.set_defaults(func=cmd_pause)

    p_output = sub.add_parser("output", help="Drain buffered stdout/stderr from the debuggee.")
    p_output.add_argument(
        "--since-last-stop",
        action="store_true",
        help="Only return output emitted since the most recent stop.",
    )
    p_output.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Limit output to the last N lines.",
    )
    _add_common_flags(p_output)
    p_output.set_defaults(func=cmd_output)

    p_setbp = sub.add_parser("set-bp", help="Add a breakpoint.")
    p_setbp.add_argument("spec", metavar="FILE:LINE[:CONDITION]")
    _add_common_flags(p_setbp)
    p_setbp.set_defaults(func=cmd_set_bp)

    p_clearbp = sub.add_parser("clear-bp", help="Remove a breakpoint by file:line.")
    p_clearbp.add_argument("spec", metavar="FILE:LINE")
    _add_common_flags(p_clearbp)
    p_clearbp.set_defaults(func=cmd_clear_bp)

    p_listbp = sub.add_parser("list-bp", help="List all tracked breakpoints.")
    _add_common_flags(p_listbp)
    p_listbp.set_defaults(func=cmd_list_bp)

    p_restart = sub.add_parser("restart", help="Re-launch the debuggee, preserving breakpoints.")
    _add_context_lines_flag(p_restart)
    _add_common_flags(p_restart)
    p_restart.set_defaults(func=cmd_restart)


# ---- emit helpers -----------------------------------------------------------


def _resolve_cwd(args: argparse.Namespace) -> Path:
    return Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()


def _emit(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    emit_payload(payload, text=args.text, pretty=args.pretty)


def _emit_error(
    args: argparse.Namespace, message: str, *, error_type: str = "usage"
) -> dict[str, Any]:
    _emit_error_payload(error_type, message, text=args.text, pretty=args.pretty)
    return {"status": "error", "error_type": error_type, "message": message}


def _parse_break_at(value: str) -> tuple[Path, int] | None:
    sep = value.rfind(":")
    if sep <= 0:
        return None
    file_part, line_part = value[:sep], value[sep + 1 :]
    try:
        line = int(line_part)
    except ValueError:
        return None
    if line < 1:
        return None
    return Path(file_part), line


# ---- wire helpers -----------------------------------------------------------


def _request(
    port: int,
    command: str,
    *,
    args: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        payload: dict[str, Any] = {"command": command}
        if args is not None:
            payload["args"] = args
        control_proto.send(sock, payload)
        resp = control_proto.recv(sock)
    if resp is None:
        return {"status": "error", "error_type": "protocol", "message": "empty response"}
    return resp


def _call_daemon(
    args: argparse.Namespace,
    command: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 60.0,
) -> int:
    """Resolve the live session, send one command, emit the result.

    Returns the CLI exit code: 0 on success, 1 if the daemon returned an
    error, 2 for client-side failures (no session, dead daemon, transport).
    """
    cwd = _resolve_cwd(args)
    meta_path = session_dir(cwd, args.session) / "meta.json"

    meta = _read_meta(meta_path)
    if meta is None:
        _emit_error(args, f"no session named {args.session!r}", error_type="no_session")
        return 2

    pid = meta.get("pid")
    if not isinstance(pid, int) or not is_pid_alive(pid):
        shutil.rmtree(meta_path.parent, ignore_errors=True)
        _emit_error(args, "session daemon is not running", error_type="dead_session")
        return 2

    control_port = meta.get("control_port")
    if not isinstance(control_port, int):
        _emit_error(args, "session meta has no control_port", error_type="dead_session")
        return 2

    try:
        resp = _request(int(control_port), command, args=payload, timeout=timeout)
    except (OSError, TimeoutError) as exc:
        _emit_error(args, f"failed to talk to session daemon: {exc}", error_type="daemon_failed")
        return 2

    if resp.get("status") != "ok":
        _emit(args, resp)
        return 1

    result = resp.get("result")
    if not isinstance(result, dict):
        _emit_error(args, "malformed daemon response", error_type="protocol")
        return 2
    _emit(args, result)
    return 0


# ---- meta.json helpers ------------------------------------------------------


def _read_meta(meta_path: Path) -> dict[str, Any] | None:
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_meta(meta_path: Path, data: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _wait_for_control_port(meta_path: Path, *, timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        meta = _read_meta(meta_path)
        if meta and isinstance(meta.get("control_port"), int):
            return int(meta["control_port"])
        time.sleep(_CONTROL_PORT_POLL_INTERVAL)
    return None


# ---- start ------------------------------------------------------------------


def cmd_start(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    # Resolve break-at specs to dicts up-front so the inline helper gets normalized input.
    breakpoints: list[dict[str, Any]] = []
    for spec in args.break_at:
        parsed = _parse_bp_with_condition(spec)
        if parsed is None:
            _emit_error(args, f"invalid --break-at {spec!r}; expected <file>:<line>[:condition]")
            return 2
        file, line, condition = parsed
        file = (cwd / file).resolve() if not file.is_absolute() else file.resolve()
        breakpoints.append({"file": str(file), "line": line, "condition": condition})

    result = start_session_inline(
        cwd=cwd,
        session_name=args.session,
        script=args.script,
        script_args=list(args.script_args or []),
        breakpoints=breakpoints,
        stop_on_entry=bool(args.stop_on_entry),
        idle_timeout=float(args.idle_timeout),
        start_timeout=float(args.start_timeout),
        context_lines=int(args.context_lines),
        listen_port=args.listen,
        use_bps_file=bool(args.use_bps_file),
        no_write_bps_file=bool(args.no_write_bps_file),
    )
    if result["status"] == "error":
        _emit_error(args, result["message"], error_type=result.get("error_type", "usage"))
        return int(result.get("exit_code", 2))
    _emit(args, result["payload"])
    return int(result.get("exit_code", 0))


def start_session_inline(
    *,
    cwd: Path,
    session_name: str,
    script: str,
    script_args: list[str],
    breakpoints: list[dict[str, Any]],
    stop_on_entry: bool = False,
    idle_timeout: float = 1800.0,
    start_timeout: float = 30.0,
    context_lines: int = 5,
    listen_port: int | None = None,
    use_bps_file: bool = False,
    no_write_bps_file: bool = False,
) -> dict[str, Any]:
    """Start a session (or VS Code listen-mode spawn) without going through argparse.

    Returns ``{"status": "ok", "payload": {...}, "exit_code": int}`` on success
    or ``{"status": "error", "error_type": ..., "message": ..., "exit_code": int}``.
    ``--listen`` short-circuits the daemon: we spawn the debuggee in
    ``debugpy --listen --wait-for-client`` mode and return its attach URL.
    """
    ensure_state_dir(cwd)
    sdir = session_dir(cwd, session_name)
    meta_path = sdir / "meta.json"

    existing = _read_meta(meta_path)
    if existing is not None:
        pid = existing.get("pid")
        if isinstance(pid, int) and is_pid_alive(pid):
            return {
                "status": "error",
                "error_type": "session_exists",
                "message": f"session {session_name!r} already running (pid={pid})",
                "exit_code": 2,
            }
        shutil.rmtree(sdir, ignore_errors=True)

    raw_script = Path(script)
    script_path = (
        (cwd / raw_script).resolve() if not raw_script.is_absolute() else raw_script.resolve()
    )
    if not script_path.exists():
        return {
            "status": "error",
            "error_type": "not_found",
            "message": f"script not found: {script_path}",
            "exit_code": 2,
        }

    if listen_port is not None:
        return _spawn_listen_mode(
            cwd=cwd,
            session_name=session_name,
            script_path=script_path,
            script_args=script_args,
            listen_port=int(listen_port),
        )

    # Optionally merge the shared breakpoints file into the initial set so the
    # daemon launches with everything the user has tracked across sessions.
    if use_bps_file:
        shared = read_breakpoints(cwd)
        # Normalize relative paths in the shared file to absolute against cwd
        # so the daemon and the file agree on identity.
        normalized: list[dict[str, Any]] = []
        for entry in shared:
            file = Path(entry["file"])
            file = (cwd / file).resolve() if not file.is_absolute() else file.resolve()
            normalized.append(
                {
                    "file": str(file),
                    "line": entry["line"],
                    "condition": entry.get("condition"),
                }
            )
        breakpoints = merge_breakpoints(breakpoints, normalized)

    sdir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "session_id": session_name,
        "script": str(script_path),
        "args": script_args,
        "cwd": str(cwd),
        "breakpoints": breakpoints,
        "stop_on_entry": stop_on_entry,
        "exception_filters": [],
        "listen_port": None,
        "idle_timeout_seconds": idle_timeout,
        "start_timeout_seconds": start_timeout,
        "source_context_lines": context_lines,
        "use_bps_file": use_bps_file,
        "write_bps_file": not no_write_bps_file,
        "pid": None,
        "control_port": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "spawning",
    }
    _write_meta(meta_path, meta)

    proc = _spawn_daemon(meta_path)

    control_port = _wait_for_control_port(meta_path, timeout=_CONTROL_PORT_POLL_TIMEOUT)
    if control_port is None:
        _terminate_daemon(proc.pid)
        shutil.rmtree(sdir, ignore_errors=True)
        return {
            "status": "error",
            "error_type": "daemon_failed",
            "message": "session daemon failed to start (no control port within timeout)",
            "exit_code": 2,
        }

    try:
        resp = _request(control_port, "start_result", timeout=max(start_timeout, 5.0))
    except (OSError, TimeoutError) as exc:
        _terminate_daemon(proc.pid)
        shutil.rmtree(sdir, ignore_errors=True)
        return {
            "status": "error",
            "error_type": "daemon_failed",
            "message": f"failed to talk to session daemon: {exc}",
            "exit_code": 2,
        }

    if resp.get("status") != "ok":
        # Surface the daemon's structured error verbatim.
        return {
            "status": "error",
            "error_type": str(resp.get("error_type") or "daemon_failed"),
            "message": str(resp.get("message") or "daemon returned error"),
            "exit_code": 2,
        }

    result = resp.get("result")
    if not isinstance(result, dict):
        return {
            "status": "error",
            "error_type": "protocol",
            "message": "malformed daemon response",
            "exit_code": 2,
        }
    return {"status": "ok", "payload": result, "exit_code": 0}


def _spawn_listen_mode(
    *,
    cwd: Path,
    session_name: str,
    script_path: Path,
    script_args: list[str],
    listen_port: int,
) -> dict[str, Any]:
    """Spawn ``python -m debugpy --listen --wait-for-client`` and return attach info.

    This is the VS Code remote-attach path. We don't connect a DAP client of
    our own — debugpy in this mode accepts a single client, so giving it to
    VS Code is the whole point. We block until the port is listening so the
    caller can start their editor with confidence.
    """
    cmd = [
        sys.executable,
        "-m",
        "debugpy",
        "--listen",
        f"127.0.0.1:{listen_port}",
        "--wait-for-client",
        str(script_path),
        *script_args,
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "cwd": str(cwd),
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = windows_no_window_flags()
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)

    if not _wait_port_listening("127.0.0.1", listen_port, timeout=10.0):
        _terminate_daemon(proc.pid)
        return {
            "status": "error",
            "error_type": "daemon_failed",
            "message": f"debugpy did not start listening on 127.0.0.1:{listen_port}",
            "exit_code": 2,
        }
    payload = {
        "status": "listening",
        "session": session_name,
        "pid": proc.pid,
        "attach_url": f"debugpy://127.0.0.1:{listen_port}",
        "host": "127.0.0.1",
        "port": listen_port,
        "script": str(script_path),
    }
    return {"status": "ok", "payload": payload, "exit_code": 0}


def _wait_port_listening(host: str, port: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _spawn_daemon(meta_path: Path) -> subprocess.Popen[bytes]:
    cmd = [sys.executable, "-m", "debug_agent.core.session_proc", str(meta_path)]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # CREATE_NO_WINDOW keeps the daemon as a console process but without a
        # visible console window. Windows doesn't tie child lifetime to the
        # parent, so the daemon still outlives the CLI without DETACHED_PROCESS.
        kwargs["creationflags"] = windows_no_window_flags()
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _terminate_daemon(pid: int) -> None:
    if pid <= 0 or not is_pid_alive(pid):
        return
    kill_tree(pid)


# ---- inspect ----------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    return _call_daemon(args, "inspect", _with_context_lines(args, {}), timeout=30.0)


def cmd_eval(args: argparse.Namespace) -> int:
    return _call_daemon(
        args,
        "eval",
        _with_context_lines(args, {"expression": args.expr, "frame": args.frame}),
        timeout=60.0,
    )


def cmd_continue(args: argparse.Namespace) -> int:
    return _call_daemon(
        args,
        "continue",
        _with_context_lines(
            args,
            {
                "add_bps": list(args.break_add or []),
                "remove_bps": list(args.break_remove or []),
                "to": args.to,
                "exception_filters": list(args.exc_filters or []),
            },
        ),
        timeout=120.0,
    )


def cmd_step(args: argparse.Namespace) -> int:
    return _call_daemon(args, "step", _with_context_lines(args, {"mode": args.mode}), timeout=60.0)


def cmd_pause(args: argparse.Namespace) -> int:
    return _call_daemon(args, "pause", {}, timeout=30.0)


def cmd_output(args: argparse.Namespace) -> int:
    return _call_daemon(
        args,
        "output",
        {"since_last_stop": bool(args.since_last_stop), "lines": args.lines},
        timeout=10.0,
    )


def cmd_set_bp(args: argparse.Namespace) -> int:
    parsed = _parse_bp_with_condition(args.spec)
    if parsed is None:
        _emit_error(args, f"invalid spec {args.spec!r}; expected <file>:<line>[:condition]")
        return 2
    file, line, cond = parsed
    cwd = _resolve_cwd(args)
    file_abs = (cwd / file).resolve() if not file.is_absolute() else file.resolve()
    return _call_daemon(
        args,
        "set_bp",
        {"file": str(file_abs), "line": line, "condition": cond},
        timeout=30.0,
    )


def cmd_clear_bp(args: argparse.Namespace) -> int:
    parsed = _parse_break_at(args.spec)
    if parsed is None:
        _emit_error(args, f"invalid spec {args.spec!r}; expected <file>:<line>")
        return 2
    file, line = parsed
    cwd = _resolve_cwd(args)
    file_abs = (cwd / file).resolve() if not file.is_absolute() else file.resolve()
    return _call_daemon(
        args,
        "clear_bp",
        {"file": str(file_abs), "line": line},
        timeout=30.0,
    )


def cmd_list_bp(args: argparse.Namespace) -> int:
    return _call_daemon(args, "list_bp", {}, timeout=10.0)


def cmd_restart(args: argparse.Namespace) -> int:
    return _call_daemon(args, "restart", _with_context_lines(args, {}), timeout=120.0)


def _parse_bp_with_condition(value: str) -> tuple[Path, int, str | None] | None:
    """Parse ``FILE:LINE[:CONDITION]`` — splits from the right to handle drive letters."""
    head, sep, tail = value.rpartition(":")
    if not sep:
        return None
    try:
        line = int(tail)
        condition: str | None = None
    except ValueError:
        condition = tail
        head2, sep2, tail2 = head.rpartition(":")
        if not sep2:
            return None
        try:
            line = int(tail2)
        except ValueError:
            return None
        head = head2
    if line < 1:
        return None
    return Path(head), line, condition


# ---- release / stop ---------------------------------------------------------


def cmd_release(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    sdir = session_dir(cwd, args.session)
    meta_path = sdir / "meta.json"

    meta = _read_meta(meta_path)
    if meta is None:
        # Idempotent — releasing a non-existent session is a no-op success.
        _emit(args, {"status": "ok", "message": "no session"})
        return 0

    pid = meta.get("pid") if isinstance(meta.get("pid"), int) else None
    control_port = meta.get("control_port") if isinstance(meta.get("control_port"), int) else None

    if control_port is not None:
        try:
            _request(int(control_port), "release", timeout=5.0)
        except (ConnectionRefusedError, ConnectionResetError):
            # Daemon already dead — fine, proceed to cleanup.
            pass
        except (OSError, TimeoutError):
            # Daemon unresponsive — fall through to force-kill below.
            pass

    if isinstance(pid, int) and pid > 0:
        deadline = time.monotonic() + _RELEASE_WAIT_TIMEOUT
        while time.monotonic() < deadline:
            if not is_pid_alive(pid):
                break
            time.sleep(0.1)
        if is_pid_alive(pid):
            kill_tree(pid)

    shutil.rmtree(sdir, ignore_errors=True)
    _emit(args, {"status": "ok"})
    return 0
