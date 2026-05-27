"""High-level DAP session: owns adapter subprocess + client + state machine.

Lifecycle: ``new`` -> ``starting`` -> ``running`` <-> ``stopped`` -> ``terminated`` -> ``released``.

The session abstracts away the DAP minutiae (thread/frame plumbing,
``initialized``/``configurationDone`` handshake, output-event buffering)
so callers can think in terms of "start, wait for stop, inspect,
continue, repeat".
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from debug_cli.adapters import debugpy_adapter
from debug_cli.core.auto_context import build_context, truncate_value
from debug_cli.core.dap_client import DapClient, DapError
from debug_cli.core.dap_types import (
    Breakpoint,
    FrameInfo,
    Location,
    SourcePreview,
    StoppedContext,
    VariableInfo,
)

__all__ = [
    "Breakpoint",
    "DapSession",
    "FrameInfo",
    "Location",
    "SourcePreview",
    "StoppedContext",
    "VariableInfo",
]


class DapSession:
    def __init__(self, session_id: str = "default", *, source_context_lines: int = 5) -> None:
        self.session_id = session_id
        self._source_context_lines = source_context_lines
        self._state: str = "new"
        self._client: DapClient | None = None
        self._adapter_proc: subprocess.Popen[bytes] | None = None
        self._current_thread_id: int | None = None
        self._output_buffer: list[str] = []
        self._last_stop_output_pos: int = 0  # char offset into joined buffer at last stop
        self._warnings: list[str] = []
        self._exit_code: int | None = None
        self._listen_port: int | None = None  # reserved for Phase 10 (attach)

    # ---- introspection -------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_thread_id(self) -> int | None:
        return self._current_thread_id

    @property
    def client(self) -> DapClient | None:
        return self._client

    @property
    def source_context_lines(self) -> int:
        return self._source_context_lines

    def set_source_context_lines(self, value: int) -> None:
        """Override the source-window size used by future stopped contexts."""
        self._source_context_lines = max(0, int(value))

    # ---- lifecycle -----------------------------------------------------------

    def start(
        self,
        *,
        script: Path,
        args: list[str] | None = None,
        cwd: Path | None = None,
        breakpoints: list[Breakpoint] | None = None,
        stop_on_entry: bool = False,
        exception_filters: list[str] | None = None,
        listen_port: int | None = None,
    ) -> None:
        if self._state != "new":
            raise RuntimeError(f"session already started (state={self._state})")
        self._state = "starting"
        self._listen_port = listen_port

        port = debugpy_adapter.find_free_port()
        self._adapter_proc = debugpy_adapter.spawn_adapter(port)
        try:
            sock = debugpy_adapter.wait_until_listening(port, timeout=10.0)
            client = DapClient()
            client.attach_socket(sock)
            self._client = client

            client.initialize()
            launch_payload: dict[str, Any] = {
                "type": "python",
                "request": "launch",
                "program": str(Path(script).resolve()),
                "console": "internalConsole",
                "python": sys.executable,
                "stopOnEntry": stop_on_entry,
            }
            if args is not None:
                launch_payload["args"] = args
            if cwd is not None:
                launch_payload["cwd"] = str(cwd)
            launch_seq = client.send_request("launch", launch_payload)

            client.wait_for_event("initialized", timeout=10.0)

            # Group breakpoints by file (DAP setBreakpoints replaces per source).
            by_file: dict[Path, list[Breakpoint]] = {}
            for bp in breakpoints or []:
                by_file.setdefault(bp.file.resolve(), []).append(bp)
            for file_path, bps in by_file.items():
                self.set_breakpoints(file_path, bps)

            client.set_exception_breakpoints(exception_filters or [])
            client.configuration_done()
            client.wait_response(launch_seq, "launch", timeout=10.0)
            self._state = "running"
        except Exception:
            # Don't leave a half-spawned adapter dangling.
            self.release()
            raise

    def release(self) -> None:
        """Best-effort cleanup. Idempotent — safe to call from ``finally``."""
        if self._state == "released":
            return
        client = self._client
        self._client = None
        if client is not None:
            with contextlib.suppress(Exception):
                client.disconnect()
        proc = self._adapter_proc
        self._adapter_proc = None
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    proc.kill()
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5.0)
        self._state = "released"

    # ---- stop/resume flow ----------------------------------------------------

    def wait_for_stop(self, *, timeout: float = 30.0) -> StoppedContext:
        """Drain events until ``stopped``, ``terminated``, or ``exited``."""
        if self._state == "released":
            raise RuntimeError("session has been released")
        if self._state == "terminated":
            return self._terminal_context()
        if self._state not in {"running", "stopped"}:
            raise RuntimeError(f"cannot wait_for_stop in state {self._state}")
        client = self._client
        if client is None:
            raise RuntimeError("no DAP client")

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DapError("wait_for_stop", f"timed out after {timeout}s")
            msg = client.poll_event(timeout=remaining)
            if msg is None:
                continue
            event_name = msg.get("event")
            body = msg.get("body") or {}
            if event_name == "output":
                self._capture_output(body)
                continue
            if event_name == "stopped":
                self._current_thread_id = int(body.get("threadId", 0))
                reason = str(body.get("reason", ""))
                self._state = "stopped"
                return self._build_stopped_context(reason)
            if event_name == "exited":
                self._exit_code = int(body.get("exitCode", 0))
                self._state = "terminated"
                # Drain any final ``terminated`` event quickly so it doesn't
                # surprise the next caller — but don't block long.
                self._drain_terminal_events(client, deadline_extra=0.5)
                return self._terminal_context()
            if event_name == "terminated":
                self._state = "terminated"
                self._drain_terminal_events(client, deadline_extra=0.5)
                return self._terminal_context()
            # Ignore all other events (thread, module, process, etc.)

    def continue_(self, *, timeout: float = 30.0) -> StoppedContext:
        self._ensure_stopped("continue")
        client = self._require_client()
        thread_id = self._require_thread_id()
        self._state = "running"
        client.continue_(thread_id)
        return self.wait_for_stop(timeout=timeout)

    def step(self, *, mode: str = "over", timeout: float = 30.0) -> StoppedContext:
        self._ensure_stopped("step")
        client = self._require_client()
        thread_id = self._require_thread_id()
        self._state = "running"
        if mode == "over":
            client.next(thread_id)
        elif mode == "in":
            client.step_in(thread_id)
        elif mode == "out":
            client.step_out(thread_id)
        else:
            raise ValueError(f"unknown step mode: {mode!r}")
        return self.wait_for_stop(timeout=timeout)

    def pause(self, *, timeout: float = 10.0) -> StoppedContext:
        if self._state != "running":
            raise RuntimeError(f"cannot pause in state {self._state}")
        client = self._require_client()
        # Pause needs a thread id. If we've never stopped, grab the first one.
        thread_id = self._current_thread_id
        if thread_id is None:
            threads_body = client.threads()
            threads = threads_body.get("threads", [])
            if not threads:
                raise RuntimeError("no threads to pause")
            thread_id = int(threads[0]["id"])
        client.pause(thread_id)
        return self.wait_for_stop(timeout=timeout)

    # ---- inspection ----------------------------------------------------------

    def set_breakpoints(self, file: Path, bps: list[Breakpoint]) -> list[dict[str, Any]]:
        """Replace breakpoints for ``file``. Records warnings for unresolved/adjusted.

        Returns the raw DAP breakpoint records. Newly-emitted warnings are
        also pushed onto :attr:`_warnings` so they surface in the next
        stopped context — and are made available via
        :meth:`set_breakpoints_with_warnings` for callers (e.g. ``set-bp``,
        ``continue --break``) that want them in their immediate response.
        """
        response_bps, _new = self.set_breakpoints_with_warnings(file, bps)
        return response_bps

    def set_breakpoints_with_warnings(
        self, file: Path, bps: list[Breakpoint]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Like :meth:`set_breakpoints` but also returns warnings from THIS call."""
        client = self._require_client()
        resolved_path = file.resolve()
        dap_bps: list[dict[str, Any]] = []
        for bp in bps:
            entry: dict[str, Any] = {"line": bp.line}
            if bp.condition is not None:
                entry["condition"] = bp.condition
            dap_bps.append(entry)
        body = client.set_breakpoints(resolved_path, dap_bps)
        response_bps: list[dict[str, Any]] = body.get("breakpoints", [])
        new_warnings: list[str] = []
        for requested, actual in zip(bps, response_bps, strict=False):
            if not actual.get("verified", False):
                new_warnings.append(f"unresolved breakpoint at {resolved_path}:{requested.line}")
            else:
                actual_line = actual.get("line")
                if actual_line is not None and int(actual_line) != requested.line:
                    new_warnings.append(
                        f"breakpoint at {resolved_path}:{requested.line} "
                        f"adjusted to line {actual_line}"
                    )
        # Keep the existing behavior: surface in the next stopped context too.
        self._warnings.extend(new_warnings)
        return response_bps, new_warnings

    def evaluate(self, expression: str, *, frame: int | None = None) -> str:
        self._ensure_stopped("evaluate")
        client = self._require_client()
        body = client.evaluate(expression, frame_id=frame)
        value = str(body.get("result", ""))
        ref = int(body.get("variablesReference", 0))
        return truncate_value(value, variables_reference=ref)

    def drain_output(self) -> str:
        """Return all buffered output and clear the buffer. Resets stop marker."""
        return self.read_output(drain=True, since_last_stop=False)

    def read_output(self, *, drain: bool = True, since_last_stop: bool = False) -> str:
        """Return buffered output.

        ``since_last_stop`` returns only what was emitted since the last stop
        event was surfaced via :meth:`_build_stopped_context`. ``drain``
        empties the buffer (and resets the stop marker) after reading.
        """
        flat = "".join(self._output_buffer)
        result = flat[self._last_stop_output_pos :] if since_last_stop else flat
        if drain:
            self._output_buffer.clear()
            self._last_stop_output_pos = 0
        return result

    # ---- internals -----------------------------------------------------------

    def _capture_output(self, body: dict[str, Any]) -> None:
        category = body.get("category", "stdout")
        if category not in {"stdout", "stderr"}:
            return
        text = str(body.get("output", ""))
        if text:
            self._output_buffer.append(text)

    def _build_stopped_context(self, reason: str) -> StoppedContext:
        client = self._require_client()
        thread_id = self._require_thread_id()
        flat = "".join(self._output_buffer)
        # Surface only the output that arrived since the previous stop —
        # otherwise every stopped context would re-report the same history.
        recent = flat[self._last_stop_output_pos :]
        # Snapshot warnings so each context reports any breakpoint issues
        # accumulated so far, then clear so we don't repeat them forever.
        warnings = list(self._warnings)
        self._warnings.clear()
        ctx = build_context(
            client,
            thread_id,
            reason=reason,
            session_id=self.session_id,
            source_context_lines=self._source_context_lines,
            recent_output=recent,
            warnings=warnings,
        )
        # Advance the stop marker so the next stop reports only new output.
        # The buffer itself is NOT cleared: ``session output`` drains it on
        # demand and ``release`` drains anything unconsumed at teardown.
        self._last_stop_output_pos = len(flat)
        return ctx

    def _terminal_context(self) -> StoppedContext:
        status = "exited" if self._exit_code is not None else "terminated"
        flat = "".join(self._output_buffer)
        recent = flat[self._last_stop_output_pos :]
        self._last_stop_output_pos = len(flat)
        warnings = list(self._warnings)
        self._warnings.clear()
        return StoppedContext(
            status=status,
            reason="",
            session_id=self.session_id,
            output=recent,
            warnings=warnings,
            exit_code=self._exit_code,
        )

    def _drain_terminal_events(self, client: DapClient, *, deadline_extra: float) -> None:
        """Pull any remaining ``terminated``/``exited``/``output`` for cleanliness."""
        end = time.monotonic() + deadline_extra
        while time.monotonic() < end:
            msg = client.poll_event(timeout=0.05)
            if msg is None:
                continue
            event = msg.get("event")
            body = msg.get("body") or {}
            if event == "output":
                self._capture_output(body)
            elif event == "exited" and self._exit_code is None:
                self._exit_code = int(body.get("exitCode", 0))

    def _require_client(self) -> DapClient:
        if self._client is None:
            raise RuntimeError("session has no active DAP client")
        return self._client

    def _require_thread_id(self) -> int:
        if self._current_thread_id is None:
            raise RuntimeError("no current thread — session has not stopped yet")
        return self._current_thread_id

    def _ensure_stopped(self, op: str) -> None:
        if self._state != "stopped":
            raise RuntimeError(f"cannot {op} in state {self._state}")
