"""Entry point for a background session process.

Invoked by ``session start`` CLI as a detached subprocess::

    python -m debug_cli.core.session_proc <meta_path>

Reads ``meta.json`` for script/breakpoints/etc., starts a ``DapSession``,
exposes a localhost control TCP socket, and runs until ``release`` (or the
idle watchdog) shuts the process down.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from debug_cli.core import control_proto
from debug_cli.core.auto_context import build_context
from debug_cli.core.dap_session import DapSession
from debug_cli.core.dap_types import Breakpoint, StoppedContext

_ACCEPT_POLL_TIMEOUT = 0.5  # how often the accept loop re-checks shutdown flag


# ---- request dispatch -------------------------------------------------------


class _SessionState:
    """Mutable bag shared by the accept loop, request handlers, and watchdog."""

    def __init__(self, session: DapSession, initial_context: StoppedContext) -> None:
        self.session = session
        self.initial_context = initial_context
        self.last_activity = time.monotonic()
        self.shutdown = threading.Event()
        self.released = False
        self.lock = threading.Lock()

    def touch(self) -> None:
        self.last_activity = time.monotonic()


def _stopped_context_to_dict(ctx: StoppedContext) -> dict[str, Any]:
    # ``asdict`` walks nested dataclasses for us; ``Path`` isn't used in
    # ``StoppedContext`` fields so the result is JSON-serialisable as-is.
    return asdict(ctx)


def _handle_request(state: _SessionState, req: dict[str, Any]) -> dict[str, Any]:
    command = req.get("command")
    if command == "start_result":
        return {"status": "ok", "result": _stopped_context_to_dict(state.initial_context)}
    if command == "inspect":
        try:
            ctx = _build_inspect_context(state)
        except RuntimeError as exc:
            return {
                "status": "error",
                "error_type": "not_stopped",
                "message": str(exc),
            }
        return {"status": "ok", "result": _stopped_context_to_dict(ctx)}
    if command == "release":
        with state.lock:
            if not state.released:
                with contextlib.suppress(Exception):
                    state.session.release()
                state.released = True
            state.shutdown.set()
        return {"status": "ok", "result": {"released": True}}
    return {
        "status": "error",
        "error_type": "unknown_command",
        "message": f"unknown command: {command!r}",
    }


def _build_inspect_context(state: _SessionState) -> StoppedContext:
    session = state.session
    client = session.client
    thread_id = session.current_thread_id
    if client is None or thread_id is None or session.state != "stopped":
        raise RuntimeError(f"session is not stopped (state={session.state})")
    return build_context(
        client,
        thread_id,
        reason="inspect",
        session_id=session.session_id,
        recent_output="",
        warnings=[],
    )


# ---- server / watchdog ------------------------------------------------------


def _accept_loop(server: socket.socket, state: _SessionState) -> None:
    server.settimeout(_ACCEPT_POLL_TIMEOUT)
    while not state.shutdown.is_set():
        try:
            conn, _addr = server.accept()
        except TimeoutError:
            continue
        except OSError:
            break
        with conn:
            state.touch()
            try:
                req = control_proto.recv(conn)
                if req is None:
                    continue
                try:
                    resp = _handle_request(state, req)
                except Exception as exc:  # noqa: BLE001
                    resp = {
                        "status": "error",
                        "error_type": "internal",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                with contextlib.suppress(OSError):
                    control_proto.send(conn, resp)
            except OSError:
                # Peer dropped mid-exchange — log and continue serving.
                print("connection error while handling request", flush=True)
                traceback.print_exc()


def _watchdog(state: _SessionState, idle_timeout: float) -> None:
    if idle_timeout <= 0:
        return
    while not state.shutdown.is_set():
        time.sleep(min(idle_timeout / 4, 10.0))
        if state.shutdown.is_set():
            return
        if time.monotonic() - state.last_activity >= idle_timeout:
            print(f"idle timeout after {idle_timeout}s — shutting down", flush=True)
            with state.lock:
                if not state.released:
                    with contextlib.suppress(Exception):
                        state.session.release()
                    state.released = True
                state.shutdown.set()
            return


def _serve(server: socket.socket, state: _SessionState, idle_timeout: float) -> None:
    watchdog = threading.Thread(
        target=_watchdog,
        args=(state, idle_timeout),
        name="session-watchdog",
        daemon=True,
    )
    watchdog.start()
    try:
        _accept_loop(server, state)
    finally:
        state.shutdown.set()
        with state.lock:
            if not state.released:
                with contextlib.suppress(Exception):
                    state.session.release()
                state.released = True


# ---- bootstrap --------------------------------------------------------------


def _open_log(session_dir_path: Path) -> Path:
    session_dir_path.mkdir(parents=True, exist_ok=True)
    log_path = session_dir_path / "log.txt"
    # Append-mode so consecutive runs don't clobber prior logs.
    log_fp = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = log_fp
    sys.stderr = log_fp
    return log_path


def _update_meta(meta_path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    data.update(updates)
    meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _bind_control_socket() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    port = sock.getsockname()[1]
    return sock, int(port)


def _breakpoints_from_meta(meta: dict[str, Any]) -> list[Breakpoint]:
    bps: list[Breakpoint] = []
    for entry in meta.get("breakpoints") or []:
        bps.append(
            Breakpoint(
                file=Path(entry["file"]),
                line=int(entry["line"]),
                condition=entry.get("condition"),
            )
        )
    return bps


def main(meta_path: Path) -> int:
    meta_path = Path(meta_path).resolve()
    session_dir_path = meta_path.parent
    _open_log(session_dir_path)
    print(f"[{datetime.now(timezone.utc).isoformat()}] session_proc starting", flush=True)

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read meta.json: {exc}", flush=True)
        return 1

    server: socket.socket | None = None
    session: DapSession | None = None
    try:
        server, control_port = _bind_control_socket()
        _update_meta(
            meta_path,
            {
                "pid": os.getpid(),
                "control_port": control_port,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "starting",
            },
        )

        session = DapSession(session_id=str(meta.get("session_id", "default")))
        script_path = Path(str(meta["script"]))
        cwd_value = meta.get("cwd")
        cwd_path = Path(str(cwd_value)) if cwd_value else None
        session.start(
            script=script_path,
            args=list(meta.get("args") or []),
            cwd=cwd_path,
            breakpoints=_breakpoints_from_meta(meta),
            stop_on_entry=bool(meta.get("stop_on_entry", False)),
            exception_filters=list(meta.get("exception_filters") or []),
            listen_port=meta.get("listen_port"),
        )
        start_timeout = float(meta.get("start_timeout_seconds") or 30.0)
        initial_context = session.wait_for_stop(timeout=start_timeout)
        _update_meta(meta_path, {"status": initial_context.status})

        state = _SessionState(session, initial_context)
        idle_timeout = float(meta.get("idle_timeout_seconds") or 1800)
        _serve(server, state, idle_timeout)
        _update_meta(meta_path, {"status": "released"})
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"unhandled error: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        with contextlib.suppress(Exception):
            _update_meta(meta_path, {"status": "error", "error_message": str(exc)})
        if session is not None:
            with contextlib.suppress(Exception):
                session.release()
        return 1
    finally:
        if server is not None:
            with contextlib.suppress(OSError):
                server.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m debug_cli.core.session_proc <meta_path>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
