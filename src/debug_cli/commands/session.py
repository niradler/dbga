"""CLI surface for ``debug-cli session start / inspect / release / stop``.

The CLI itself is stateless: it spawns a detached background Python process
(``debug_cli.core.session_proc``) that owns the live ``DapSession``, then
talks to it over a localhost TCP control socket via length-prefixed JSON.

Subsequent commands re-read ``.debug-cli/sessions/<name>/meta.json`` to
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

from debug_cli.core import control_proto
from debug_cli.core.format import format_json, format_text
from debug_cli.core.process import kill_tree
from debug_cli.core.state import (
    ensure_state_dir,
    is_pid_alive,
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
        help="Breakpoint as <file>:<line>. Repeatable.",
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
    _add_common_flags(p_start)
    p_start.add_argument("script", help="Path to the Python script to debug.")
    p_start.add_argument(
        "script_args",
        nargs="*",
        help="Args passed to the script (no leading-dash args supported in this phase).",
    )
    p_start.set_defaults(func=cmd_start)

    p_inspect = sub.add_parser("inspect", help="Re-read the current stopped state.")
    _add_common_flags(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect)

    p_release = sub.add_parser("release", help="Tear down the background session.")
    _add_common_flags(p_release)
    p_release.set_defaults(func=cmd_release)

    p_stop = sub.add_parser("stop", help="Alias for 'release'.")
    _add_common_flags(p_stop)
    p_stop.set_defaults(func=cmd_release)


# ---- emit helpers -----------------------------------------------------------


def _resolve_cwd(args: argparse.Namespace) -> Path:
    return Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()


def _emit(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    if args.text:
        print(format_text(payload))
    else:
        print(format_json(payload, pretty=args.pretty))


def _emit_error(
    args: argparse.Namespace, message: str, *, error_type: str = "usage"
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "error", "error_type": error_type, "message": message}
    _emit(args, payload)
    return payload


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


def _request(port: int, command: str, *, timeout: float = 30.0) -> dict[str, Any]:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        control_proto.send(sock, {"command": command})
        resp = control_proto.recv(sock)
    if resp is None:
        return {"status": "error", "error_type": "protocol", "message": "empty response"}
    return resp


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
    ensure_state_dir(cwd)
    sdir = session_dir(cwd, args.session)
    meta_path = sdir / "meta.json"

    existing = _read_meta(meta_path)
    if existing is not None:
        pid = existing.get("pid")
        if isinstance(pid, int) and is_pid_alive(pid):
            _emit_error(
                args,
                f"session {args.session!r} already running (pid={pid})",
                error_type="session_exists",
            )
            return 2
        # Stale meta — clean up so we can re-use the directory.
        shutil.rmtree(sdir, ignore_errors=True)

    # Resolve breakpoints against cwd.
    breakpoints: list[dict[str, Any]] = []
    for spec in args.break_at:
        parsed = _parse_break_at(spec)
        if parsed is None:
            _emit_error(args, f"invalid --break-at {spec!r}; expected <file>:<line>")
            return 2
        file, line = parsed
        file = (cwd / file).resolve() if not file.is_absolute() else file.resolve()
        breakpoints.append({"file": str(file), "line": line, "condition": None})

    script = Path(args.script)
    script = (cwd / script).resolve() if not script.is_absolute() else script.resolve()
    if not script.exists():
        _emit_error(args, f"script not found: {script}", error_type="not_found")
        return 2

    script_args = list(args.script_args or [])

    sdir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "session_id": args.session,
        "script": str(script),
        "args": script_args,
        "cwd": str(cwd),
        "breakpoints": breakpoints,
        "stop_on_entry": bool(args.stop_on_entry),
        "exception_filters": [],
        "listen_port": None,
        "idle_timeout_seconds": float(args.idle_timeout),
        "start_timeout_seconds": float(args.start_timeout),
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
        _emit_error(
            args,
            "session daemon failed to start (no control port within timeout)",
            error_type="daemon_failed",
        )
        return 2

    try:
        resp = _request(control_port, "start_result", timeout=max(args.start_timeout, 5.0))
    except (OSError, TimeoutError) as exc:
        _terminate_daemon(proc.pid)
        shutil.rmtree(sdir, ignore_errors=True)
        _emit_error(args, f"failed to talk to session daemon: {exc}", error_type="daemon_failed")
        return 2

    if resp.get("status") != "ok":
        _emit(args, resp)
        return 2

    result = resp.get("result")
    if not isinstance(result, dict):
        _emit_error(args, "malformed daemon response", error_type="protocol")
        return 2
    _emit(args, result)
    return 0


def _spawn_daemon(meta_path: Path) -> subprocess.Popen[bytes]:
    cmd = [sys.executable, "-m", "debug_cli.core.session_proc", str(meta_path)]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS lets the daemon outlive the CLI without inheriting
        # the console; CREATE_NEW_PROCESS_GROUP gives it its own group so
        # Ctrl+C on the CLI doesn't propagate.
        DETACHED_PROCESS = 0x00000008
        kwargs["creationflags"] = DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _terminate_daemon(pid: int) -> None:
    if pid <= 0 or not is_pid_alive(pid):
        return
    kill_tree(pid)


# ---- inspect ----------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    cwd = _resolve_cwd(args)
    sdir = session_dir(cwd, args.session)
    meta_path = sdir / "meta.json"

    meta = _read_meta(meta_path)
    if meta is None:
        _emit_error(args, f"no session named {args.session!r}", error_type="no_session")
        return 2

    pid = meta.get("pid")
    if not isinstance(pid, int) or not is_pid_alive(pid):
        shutil.rmtree(sdir, ignore_errors=True)
        _emit_error(args, "session daemon is not running", error_type="dead_session")
        return 2

    control_port = meta.get("control_port")
    if not isinstance(control_port, int):
        _emit_error(args, "session meta has no control_port", error_type="dead_session")
        return 2

    try:
        resp = _request(control_port, "inspect", timeout=30.0)
    except (OSError, TimeoutError) as exc:
        _emit_error(args, f"failed to talk to session daemon: {exc}", error_type="daemon_failed")
        return 2

    if resp.get("status") != "ok":
        _emit(args, resp)
        return 2

    result = resp.get("result")
    if not isinstance(result, dict):
        _emit_error(args, "malformed daemon response", error_type="protocol")
        return 2
    _emit(args, result)
    return 0


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
