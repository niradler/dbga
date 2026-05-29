"""High-level DAP session: owns adapter subprocess + client + state machine.

Lifecycle: ``new`` -> ``starting`` -> ``running`` <-> ``stopped`` -> ``terminated`` -> ``released``.

The session abstracts away the DAP minutiae (thread/frame plumbing,
``initialized``/``configurationDone`` handshake, output-event buffering)
so callers can think in terms of "start, wait for stop, inspect,
continue, repeat".
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from debug_agent.adapters import find_free_port, get_adapter, wait_until_listening
from debug_agent.adapters.base import Adapter
from debug_agent.core.auto_context import build_context, truncate_value
from debug_agent.core.dap_client import DapClient, DapError
from debug_agent.core.dap_types import (
    Breakpoint,
    FrameInfo,
    Location,
    SourcePreview,
    StoppedContext,
    VariableInfo,
)
from debug_agent.core.process import kill_tree

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
    def __init__(
        self,
        session_id: str = "default",
        *,
        source_context_lines: int = 5,
        adapter: Adapter | None = None,
    ) -> None:
        self.session_id = session_id
        self._source_context_lines = source_context_lines
        # Default to the Python adapter for backwards compatibility; callers
        # that target other languages pass an explicit adapter instance.
        self._adapter: Adapter = adapter if adapter is not None else get_adapter("python")
        self._state: str = "new"
        self._client: DapClient | None = None
        # Some DAP servers (notably vscode-js-debug) delegate every launched
        # program to a CHILD DAP session via a reverse ``startDebugging``
        # request. We open a fresh TCP connection to the same server for
        # each child and track them here. ``_active_client`` is the client
        # that owns the "real" debuggee — defaults to the parent, gets
        # reassigned to the newest child when startDebugging fires.
        self._adapter_host: str = "127.0.0.1"
        self._adapter_port: int = 0
        self._child_clients: list[DapClient] = []
        self._active_client: DapClient | None = None
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

    @property
    def adapter(self) -> Adapter:
        return self._adapter

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

        port = find_free_port()
        self._adapter_port = port
        self._adapter_proc = self._adapter.spawn_adapter(port)
        try:
            sock = wait_until_listening(
                port,
                timeout=30.0,
                proc=self._adapter_proc,
                adapter_label=f"{self._adapter.name} DAP adapter",
            )
            client = DapClient()
            client.attach_socket(sock)
            self._client = client
            self._active_client = client
            # Adapters that delegate to child sessions (vscode-js-debug)
            # will send this reverse-request after their initial ``launch``.
            # Harmless to register for adapters that never send it.
            client.register_reverse_handler("startDebugging", self._on_start_debugging)

            client.initialize()
            launch_payload: dict[str, Any] = self._adapter.launch_payload(
                script=Path(script),
                args=args,
                cwd=cwd,
                stop_on_entry=stop_on_entry,
            )
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
        """Best-effort cleanup. Idempotent — safe to call from ``finally``.

        Tree-kills the adapter process group so the debuggee (a child of the
        adapter) is torn down with it. The DAP ``disconnect`` request goes
        first to give the adapter a graceful-shutdown chance; the tree-kill
        is the unconditional fallback. Child sessions (vscode-js-debug
        spawns one per launched program) are disconnected first so they
        don't leak.
        """
        if self._state == "released":
            return
        # Tear down child sessions before the parent, so the parent is
        # still alive to receive their disconnect frames.
        for child in self._child_clients:
            with contextlib.suppress(Exception):
                child.disconnect()
        self._child_clients = []
        self._active_client = None
        client = self._client
        self._client = None
        if client is not None:
            with contextlib.suppress(Exception):
                client.disconnect()
        proc = self._adapter_proc
        self._adapter_proc = None
        if proc is not None and proc.poll() is None:
            # First, give the adapter a moment to exit on its own after the
            # graceful disconnect. If it doesn't, tree-kill the whole process
            # group so the debuggee child goes with it.
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    kill_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5.0)
        self._state = "released"

    # ---- stop/resume flow ----------------------------------------------------

    def wait_for_stop(self, *, timeout: float = 30.0) -> StoppedContext:
        """Drain events until ``stopped``, ``terminated``, or ``exited``.

        Polls the parent client AND any child clients (vscode-js-debug
        creates one child per launched program). Whichever client emits
        ``stopped`` becomes the new active client so subsequent
        ``continue_`` / ``step`` / ``evaluate`` calls route to the right
        place.
        """
        if self._state == "released":
            raise RuntimeError("session has been released")
        if self._state == "terminated":
            return self._terminal_context()
        if self._state not in {"running", "stopped"}:
            raise RuntimeError(f"cannot wait_for_stop in state {self._state}")
        if self._client is None:
            raise RuntimeError("no DAP client")

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DapError("wait_for_stop", f"timed out after {timeout}s")
            msg, source = self._poll_any_client(timeout=min(remaining, 0.2))
            if msg is None:
                continue
            event_name = msg.get("event")
            body = msg.get("body") or {}
            if event_name == "output":
                self._capture_output(body)
                continue
            if event_name == "stopped":
                self._current_thread_id = int(body.get("threadId", 0))
                # The client that emitted ``stopped`` owns the live debuggee
                # from now on. For multi-process js-debug runs, this might
                # switch back and forth across child sessions.
                self._active_client = source
                reason = str(body.get("reason", ""))
                self._state = "stopped"
                return self._build_stopped_context(reason)
            if event_name == "exited":
                # A child exited. If there are other live children (or the
                # parent is still doing work), keep waiting — only the LAST
                # exit ends the session. v1 simplification: treat any exit
                # as final since dbga targets single-process debug.
                self._exit_code = int(body.get("exitCode", 0))
                self._state = "terminated"
                self._drain_terminal_events_all(deadline_extra=0.5)
                return self._terminal_context()
            if event_name == "terminated":
                self._state = "terminated"
                self._drain_terminal_events_all(deadline_extra=0.5)
                return self._terminal_context()
            # Ignore all other events (thread, module, process, etc.)

    def _poll_any_client(self, *, timeout: float) -> tuple[dict[str, Any] | None, DapClient | None]:
        """Round-robin poll the parent + every child client for one event.

        Returns ``(msg, client_that_emitted_it)`` or ``(None, None)`` on
        timeout. Uses small per-client slices to approximate ``select``.
        """
        clients = self._live_clients()
        if not clients:
            return None, None
        per_slice = max(0.01, timeout / max(1, len(clients)))
        for client in clients:
            msg = client.poll_event(timeout=per_slice)
            if msg is not None:
                return msg, client
        return None, None

    def _live_clients(self) -> list[DapClient]:
        """Parent + child clients, in poll order (children first — they own the live debuggee)."""
        out: list[DapClient] = []
        # Children first so that for vscode-js-debug, the actually-stopping
        # session's events surface promptly instead of being starved by
        # bookkeeping events on the parent.
        out.extend(self._child_clients)
        if self._client is not None:
            out.append(self._client)
        return out

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

    def _drain_terminal_events_all(self, *, deadline_extra: float) -> None:
        """Drain trailing events from the parent and every child connection."""
        for client in self._live_clients():
            self._drain_terminal_events(client, deadline_extra=deadline_extra)

    def _require_client(self) -> DapClient:
        """Return the client owning the live debuggee.

        For adapters that delegate to a child session (vscode-js-debug),
        this is the most recent child. For everything else it's the parent.
        """
        client = self._active_client or self._client
        if client is None:
            raise RuntimeError("session has no active DAP client")
        return client

    def _on_start_debugging(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handler for vscode-js-debug's ``startDebugging`` reverse-request.

        js-debug routes every launched program through a child DAP session
        on a fresh TCP connection to the same server. We open that
        connection, run the standard handshake using the configuration the
        server gave us, and track the child so the rest of the session
        machinery sees its events. Returns an empty body (DAP requires a
        response; the body is unused).

        The handler runs on the parent client's reader thread. It MUST
        only do I/O against the child connection it opens — never against
        the parent — or the reader would deadlock waiting for events it
        also needs to read.
        """
        configuration = args.get("configuration") or {}
        request_type = str(args.get("request") or "launch")
        if request_type not in {"launch", "attach"}:
            raise RuntimeError(f"unsupported startDebugging request: {request_type!r}")

        sock = socket.create_connection((self._adapter_host, self._adapter_port), timeout=10.0)
        child = DapClient()
        child.attach_socket(sock)
        # js-debug nests sessions (e.g. parent → worker thread → child_process).
        # Register the same handler recursively so grandchildren also wire up.
        child.register_reverse_handler("startDebugging", self._on_start_debugging)

        # Standard DAP handshake on the child. Configuration is whatever the
        # parent told us to pass; we treat it as opaque and forward verbatim.
        child.initialize()
        child_seq = child.send_request(request_type, configuration)
        child.wait_for_event("initialized", timeout=15.0)
        child.set_exception_breakpoints([])
        child.configuration_done()
        child.wait_response(child_seq, request_type, timeout=15.0)

        self._child_clients.append(child)
        self._active_client = child
        # DAP startDebugging response body is unspecified; empty is correct.
        return {}

    def _require_thread_id(self) -> int:
        if self._current_thread_id is None:
            raise RuntimeError("no current thread — session has not stopped yet")
        return self._current_thread_id

    def _ensure_stopped(self, op: str) -> None:
        if self._state != "stopped":
            raise RuntimeError(f"cannot {op} in state {self._state}")
