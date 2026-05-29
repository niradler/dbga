"""Entry point for a background session process.

Invoked by ``session start`` CLI as a detached subprocess::

    python -m debug_agent.core.session_proc <meta_path>

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
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from debug_agent.adapters import get_adapter
from debug_agent.core import control_proto
from debug_agent.core.auto_context import build_context
from debug_agent.core.dap_client import DapError
from debug_agent.core.dap_session import DapSession
from debug_agent.core.dap_types import Breakpoint, StoppedContext
from debug_agent.core.state import (
    merge_breakpoints,
    read_breakpoints,
    remove_breakpoint,
    write_breakpoints,
)

_ACCEPT_POLL_TIMEOUT = 0.5  # how often the accept loop re-checks shutdown flag
_DEFAULT_OP_TIMEOUT = 30.0


# ---- request dispatch -------------------------------------------------------


class _SessionState:
    """Mutable bag shared by the accept loop, request handlers, and watchdog."""

    def __init__(
        self,
        session: DapSession,
        initial_context: StoppedContext,
        *,
        bps_by_file: dict[Path, list[Breakpoint]],
        start_meta: dict[str, Any],
    ) -> None:
        self.session = session
        self.initial_context = initial_context
        self.bps_by_file = bps_by_file
        # Lines (per resolved file) that came from a ``continue --to`` and must
        # be removed automatically once the run actually stops at them.
        self.temp_bps: dict[Path, set[int]] = {}
        self.start_meta = start_meta
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


def _bp_to_dict(bp: Breakpoint) -> dict[str, Any]:
    return {"file": str(bp.file), "line": bp.line, "condition": bp.condition}


def _parse_bp_spec(spec: str, *, allow_condition: bool = True) -> Breakpoint | None:
    """Parse ``FILE:LINE[:CONDITION]`` into a ``Breakpoint`` (file resolved).

    Splits from the RIGHT to be robust against Windows drive-letter colons in
    the file part (e.g. ``C:\\src\\foo.py:10``). ``LINE`` is the rightmost int
    segment; anything after a third colon becomes ``CONDITION``.
    """
    if not spec:
        return None
    # Try to extract a condition first: ``file:line:cond``. We do this by
    # peeling off the rightmost segments — line must be an int, anything to
    # its right is the condition.
    head, sep, tail = spec.rpartition(":")
    if not sep:
        return None
    # If ``tail`` isn't an int, ``head:tail`` may be ``file:line:cond``.
    try:
        line = int(tail)
        condition: str | None = None
    except ValueError:
        if not allow_condition:
            return None
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
    return Breakpoint(file=Path(head).resolve(), line=line, condition=condition)


def _bp_key(file: Path) -> Path:
    return file.resolve()


def _shared_bps_cwd(state: _SessionState) -> Path | None:
    """Return the cwd under which to persist the shared breakpoints file, if enabled."""
    if not state.start_meta.get("write_bps_file", True):
        return None
    cwd_value = state.start_meta.get("cwd")
    return Path(str(cwd_value)) if cwd_value else None


def _shared_bps_add(state: _SessionState, bp: Breakpoint) -> None:
    cwd = _shared_bps_cwd(state)
    if cwd is None:
        return
    with contextlib.suppress(OSError):
        existing = read_breakpoints(cwd)
        merged = merge_breakpoints(
            existing,
            [{"file": str(bp.file), "line": bp.line, "condition": bp.condition}],
        )
        write_breakpoints(cwd, merged)


def _shared_bps_remove(state: _SessionState, file: Path, line: int) -> None:
    cwd = _shared_bps_cwd(state)
    if cwd is None:
        return
    with contextlib.suppress(OSError):
        existing = read_breakpoints(cwd)
        updated = remove_breakpoint(existing, str(file), line)
        if updated != existing:
            write_breakpoints(cwd, updated)


_Handler = Callable[["_SessionState", dict[str, Any]], dict[str, Any]]


def _handle_request(state: _SessionState, req: dict[str, Any]) -> dict[str, Any]:
    command = req.get("command")
    args = req.get("args") or {}
    if not isinstance(command, str):
        return {
            "status": "error",
            "error_type": "usage",
            "message": "command must be a string",
        }
    handler = _HANDLERS.get(command)
    if handler is None:
        return {
            "status": "error",
            "error_type": "unknown_command",
            "message": f"unknown command: {command!r}",
        }
    # Per-request override of the source-window size used by any context
    # this handler builds. We persist the new value on the session so that
    # ``inspect`` and subsequent stops keep the caller's preference.
    raw_cl = args.get("context_lines")
    if isinstance(raw_cl, int) and raw_cl >= 0:
        state.session.set_source_context_lines(raw_cl)
    try:
        return handler(state, args)
    except DapError as exc:
        return {"status": "error", "error_type": "dap", "message": str(exc)}
    except RuntimeError as exc:
        return {"status": "error", "error_type": "runtime", "message": str(exc)}


def _handle_start_result(state: _SessionState, _args: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "result": _stopped_context_to_dict(state.initial_context)}


def _handle_inspect(state: _SessionState, _args: dict[str, Any]) -> dict[str, Any]:
    ctx = _build_inspect_context(state)
    return {"status": "ok", "result": _stopped_context_to_dict(ctx)}


def _handle_release(state: _SessionState, _args: dict[str, Any]) -> dict[str, Any]:
    with state.lock:
        if not state.released:
            # Surface any unconsumed output to the log before tearing down so
            # operators can see what the debuggee printed.
            with contextlib.suppress(Exception):
                leftover = state.session.read_output(drain=True)
                if leftover:
                    print("[release] unconsumed output:\n" + leftover, flush=True)
            with contextlib.suppress(Exception):
                state.session.release()
            state.released = True
        state.shutdown.set()
    return {"status": "ok", "result": {"released": True}}


def _handle_eval(state: _SessionState, args: dict[str, Any]) -> dict[str, Any]:
    expression = args.get("expression")
    if not isinstance(expression, str) or not expression:
        return {"status": "error", "error_type": "usage", "message": "expression is required"}
    raw_frame = args.get("frame")
    frame: int | None = raw_frame if isinstance(raw_frame, int) else None
    session = state.session
    # If the caller didn't pin a frame, evaluate in the live top frame so
    # ``locals`` reflect the user's actual current stop (not where we started).
    if frame is None:
        client = session.client
        tid = session.current_thread_id
        if client is not None and tid is not None and session.state == "stopped":
            with contextlib.suppress(DapError):
                stack_body = client.stack_trace(tid, levels=1)
                frames = stack_body.get("stackFrames", [])
                if frames:
                    frame = int(frames[0].get("id", 0))
    value = session.evaluate(expression, frame=frame)
    return {"status": "ok", "result": {"result": value}}


def _apply_bp_updates(
    state: _SessionState,
    *,
    add: list[Breakpoint],
    remove: list[tuple[Path, int]],
    temp: list[Breakpoint] | None = None,
) -> None:
    touched: set[Path] = set()
    for bp in add:
        key = _bp_key(bp.file)
        existing = list(state.bps_by_file.get(key, []))
        # Replace any existing entry for the same line so condition updates win.
        existing = [b for b in existing if b.line != bp.line]
        existing.append(bp)
        state.bps_by_file[key] = existing
        touched.add(key)
    for file, line in remove:
        key = _bp_key(file)
        current = state.bps_by_file.get(key)
        if not current:
            continue
        filtered = [b for b in current if b.line != line]
        if filtered:
            state.bps_by_file[key] = filtered
        else:
            state.bps_by_file.pop(key, None)
        touched.add(key)
    for bp in temp or []:
        key = _bp_key(bp.file)
        existing = list(state.bps_by_file.get(key, []))
        if not any(b.line == bp.line for b in existing):
            existing.append(bp)
        state.bps_by_file[key] = existing
        state.temp_bps.setdefault(key, set()).add(bp.line)
        touched.add(key)
    # Push the merged set per touched file.
    for key in touched:
        state.session.set_breakpoints(key, state.bps_by_file.get(key, []))


def _cleanup_temp_after_stop(state: _SessionState, ctx: StoppedContext) -> None:
    """If the stop happened at a ``--to`` temp breakpoint, remove it."""
    if not state.temp_bps:
        return
    if ctx.status != "stopped" or ctx.location is None:
        # The script terminated/exited — drop all temps.
        for key in list(state.temp_bps.keys()):
            _drop_temp_bps_for(state, key)
        return
    stop_file = Path(ctx.location.file).resolve()
    stop_line = int(ctx.location.line)
    temp_lines = state.temp_bps.get(stop_file)
    if not temp_lines or stop_line not in temp_lines:
        return
    temp_lines.discard(stop_line)
    if not temp_lines:
        state.temp_bps.pop(stop_file, None)
    existing = state.bps_by_file.get(stop_file, [])
    filtered = [b for b in existing if b.line != stop_line]
    if filtered:
        state.bps_by_file[stop_file] = filtered
    else:
        state.bps_by_file.pop(stop_file, None)
    with contextlib.suppress(DapError, RuntimeError):
        state.session.set_breakpoints(stop_file, filtered)


def _drop_temp_bps_for(state: _SessionState, key: Path) -> None:
    lines = state.temp_bps.pop(key, set())
    existing = state.bps_by_file.get(key, [])
    filtered = [b for b in existing if b.line not in lines]
    if filtered:
        state.bps_by_file[key] = filtered
    else:
        state.bps_by_file.pop(key, None)
    with contextlib.suppress(DapError, RuntimeError):
        state.session.set_breakpoints(key, filtered)


def _handle_continue(state: _SessionState, args: dict[str, Any]) -> dict[str, Any]:
    add_specs = args.get("add_bps") or []
    remove_specs = args.get("remove_bps") or []
    to_spec = args.get("to")
    exc_filters = args.get("exception_filters") or []

    add: list[Breakpoint] = []
    for spec in add_specs:
        bp = _parse_bp_spec(str(spec))
        if bp is None:
            return {"status": "error", "error_type": "usage", "message": f"bad --break {spec!r}"}
        add.append(bp)

    remove: list[tuple[Path, int]] = []
    for spec in remove_specs:
        bp = _parse_bp_spec(str(spec), allow_condition=False)
        if bp is None:
            return {
                "status": "error",
                "error_type": "usage",
                "message": f"bad --remove-break {spec!r}",
            }
        remove.append((bp.file, bp.line))

    temp: list[Breakpoint] = []
    if to_spec is not None:
        bp = _parse_bp_spec(str(to_spec), allow_condition=False)
        if bp is None:
            return {"status": "error", "error_type": "usage", "message": f"bad --to {to_spec!r}"}
        temp.append(bp)

    _apply_bp_updates(state, add=add, remove=remove, temp=temp)

    if exc_filters:
        client = state.session.client
        if client is None:
            return {"status": "error", "error_type": "runtime", "message": "no DAP client"}
        client.set_exception_breakpoints([str(f) for f in exc_filters])

    next_ctx = state.session.continue_(timeout=_DEFAULT_OP_TIMEOUT)
    _cleanup_temp_after_stop(state, next_ctx)
    return {"status": "ok", "result": _stopped_context_to_dict(next_ctx)}


def _handle_step(state: _SessionState, args: dict[str, Any]) -> dict[str, Any]:
    mode = str(args.get("mode") or "over")
    if mode not in {"over", "in", "out"}:
        return {"status": "error", "error_type": "usage", "message": f"bad step mode {mode!r}"}
    ctx = state.session.step(mode=mode, timeout=_DEFAULT_OP_TIMEOUT)
    _cleanup_temp_after_stop(state, ctx)
    return {"status": "ok", "result": _stopped_context_to_dict(ctx)}


def _handle_pause(state: _SessionState, _args: dict[str, Any]) -> dict[str, Any]:
    if state.session.state == "stopped":
        return {
            "status": "error",
            "error_type": "already_stopped",
            "message": "session is already stopped",
        }
    if state.session.state != "running":
        return {
            "status": "error",
            "error_type": "not_running",
            "message": f"cannot pause in state {state.session.state}",
        }
    ctx = state.session.pause(timeout=10.0)
    return {"status": "ok", "result": _stopped_context_to_dict(ctx)}


def _handle_output(state: _SessionState, args: dict[str, Any]) -> dict[str, Any]:
    since_last_stop = bool(args.get("since_last_stop"))
    text = state.session.read_output(drain=True, since_last_stop=since_last_stop)
    lines_arg = args.get("lines")
    if isinstance(lines_arg, int) and lines_arg > 0:
        lines = text.splitlines(keepends=True)
        text = "".join(lines[-lines_arg:])
    return {"status": "ok", "result": {"output": text}}


def _handle_set_bp(state: _SessionState, args: dict[str, Any]) -> dict[str, Any]:
    file_str = args.get("file")
    line = args.get("line")
    condition = args.get("condition")
    if not isinstance(file_str, str) or not isinstance(line, int):
        return {"status": "error", "error_type": "usage", "message": "file and line are required"}
    key = _bp_key(Path(file_str))
    bp = Breakpoint(file=key, line=int(line), condition=condition)
    existing = [b for b in state.bps_by_file.get(key, []) if b.line != bp.line]
    existing.append(bp)
    state.bps_by_file[key] = existing
    dap_bps, warnings = state.session.set_breakpoints_with_warnings(key, existing)
    _shared_bps_add(state, bp)
    return {"status": "ok", "result": {"breakpoints": dap_bps, "warnings": warnings}}


def _handle_clear_bp(state: _SessionState, args: dict[str, Any]) -> dict[str, Any]:
    file_str = args.get("file")
    line = args.get("line")
    if not isinstance(file_str, str) or not isinstance(line, int):
        return {"status": "error", "error_type": "usage", "message": "file and line are required"}
    key = _bp_key(Path(file_str))
    existing = [b for b in state.bps_by_file.get(key, []) if b.line != int(line)]
    if existing:
        state.bps_by_file[key] = existing
    else:
        state.bps_by_file.pop(key, None)
    dap_bps = state.session.set_breakpoints(key, existing)
    # Also clean from temp set so we don't try to remove it again later.
    if key in state.temp_bps:
        state.temp_bps[key].discard(int(line))
        if not state.temp_bps[key]:
            state.temp_bps.pop(key, None)
    _shared_bps_remove(state, key, int(line))
    return {"status": "ok", "result": {"breakpoints": dap_bps}}


def _handle_list_bp(state: _SessionState, _args: dict[str, Any]) -> dict[str, Any]:
    flat: list[dict[str, Any]] = []
    for bps in state.bps_by_file.values():
        for bp in bps:
            flat.append(_bp_to_dict(bp))
    return {"status": "ok", "result": {"breakpoints": flat}}


def _handle_restart(state: _SessionState, _args: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[Path, list[Breakpoint]] = {
        k: [Breakpoint(file=b.file, line=b.line, condition=b.condition) for b in v]
        for k, v in state.bps_by_file.items()
    }
    meta = state.start_meta
    with contextlib.suppress(Exception):
        state.session.release()

    # Reuse the existing adapter on restart — same language, same target.
    new_session = DapSession(
        session_id=str(meta.get("session_id", "default")),
        source_context_lines=state.session.source_context_lines,
        adapter=state.session.adapter,
    )
    script_path = Path(str(meta["script"]))
    cwd_value = meta.get("cwd")
    cwd_path = Path(str(cwd_value)) if cwd_value else None

    all_bps: list[Breakpoint] = []
    for bps in snapshot.values():
        all_bps.extend(bps)

    try:
        new_session.start(
            script=script_path,
            args=list(meta.get("args") or []),
            cwd=cwd_path,
            breakpoints=all_bps,
            stop_on_entry=bool(meta.get("stop_on_entry", False)),
            exception_filters=list(meta.get("exception_filters") or []),
            listen_port=meta.get("listen_port"),
        )
        start_timeout = float(meta.get("start_timeout_seconds") or 30.0)
        new_ctx = new_session.wait_for_stop(timeout=start_timeout)
    except Exception as exc:  # noqa: BLE001
        # Couldn't bring the new session up — clean up the half-spawned adapter
        # and tear the daemon down so the caller doesn't talk to a corpse.
        with contextlib.suppress(Exception):
            new_session.release()
        state.released = True
        state.shutdown.set()
        return {
            "status": "error",
            "error_type": "restart_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }

    state.session = new_session
    state.initial_context = new_ctx
    state.bps_by_file = snapshot
    state.temp_bps = {}
    return {"status": "ok", "result": _stopped_context_to_dict(new_ctx)}


_HANDLERS: dict[str, _Handler] = {
    "start_result": _handle_start_result,
    "inspect": _handle_inspect,
    "release": _handle_release,
    "eval": _handle_eval,
    "continue": _handle_continue,
    "step": _handle_step,
    "pause": _handle_pause,
    "output": _handle_output,
    "set_bp": _handle_set_bp,
    "clear_bp": _handle_clear_bp,
    "list_bp": _handle_list_bp,
    "restart": _handle_restart,
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
        source_context_lines=session.source_context_lines,
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
                file=Path(entry["file"]).resolve(),
                line=int(entry["line"]),
                condition=entry.get("condition"),
            )
        )
    return bps


def _group_bps_by_file(bps: list[Breakpoint]) -> dict[Path, list[Breakpoint]]:
    out: dict[Path, list[Breakpoint]] = {}
    for bp in bps:
        out.setdefault(bp.file.resolve(), []).append(bp)
    return out


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

        # ``lang`` is written by ``session start`` (auto-detected or --lang).
        # Older meta.json files from before the multi-language refactor omit
        # it; default to Python so existing sessions still resume cleanly.
        lang = str(meta.get("lang") or "python")
        try:
            adapter = get_adapter(lang)
        except ValueError as exc:
            print(f"unknown language {lang!r}: {exc}", flush=True)
            return 1
        session = DapSession(
            session_id=str(meta.get("session_id", "default")),
            source_context_lines=int(meta.get("source_context_lines") or 5),
            adapter=adapter,
        )
        script_path = Path(str(meta["script"]))
        cwd_value = meta.get("cwd")
        cwd_path = Path(str(cwd_value)) if cwd_value else None
        initial_bps = _breakpoints_from_meta(meta)
        session.start(
            script=script_path,
            args=list(meta.get("args") or []),
            cwd=cwd_path,
            breakpoints=initial_bps,
            stop_on_entry=bool(meta.get("stop_on_entry", False)),
            exception_filters=list(meta.get("exception_filters") or []),
            listen_port=meta.get("listen_port"),
        )
        start_timeout = float(meta.get("start_timeout_seconds") or 30.0)
        initial_context = session.wait_for_stop(timeout=start_timeout)
        _update_meta(meta_path, {"status": initial_context.status})

        state = _SessionState(
            session,
            initial_context,
            bps_by_file=_group_bps_by_file(initial_bps),
            start_meta=meta,
        )
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
        print("usage: python -m debug_agent.core.session_proc <meta_path>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
