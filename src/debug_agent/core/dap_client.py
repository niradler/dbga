"""Debug Adapter Protocol (DAP) client over TCP.

Implements the JSON-RPC-style wire format described at
https://microsoft.github.io/debug-adapter-protocol/ with HTTP-style
``Content-Length`` framing. A background reader thread routes incoming
messages: responses unblock the corresponding ``request`` call, events
land on a thread-safe queue for callers to consume, and server-to-client
("reverse") requests are dispatched to registered handlers — needed for
vscode-js-debug's ``startDebugging`` child-session pattern.
"""

from __future__ import annotations

import contextlib
import json
import queue
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Type for reverse-request handlers: receives ``arguments`` dict, returns the
# response ``body`` (or ``None`` for no body). Raising returns ``success: false``.
ReverseHandler = Callable[[dict[str, Any]], dict[str, Any] | None]


class DapError(Exception):
    """Raised when a DAP request fails or the connection drops."""

    def __init__(self, command: str, message: str) -> None:
        super().__init__(f"{command}: {message}")
        self.command = command
        self.message = message


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    body: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    error: str = ""


class DapClient:
    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._seq_lock = threading.Lock()
        self._seq = 0
        self._send_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._closed = threading.Event()
        # Bytes that were over-read from the socket past a header boundary —
        # consumed by both _recv_headers (for the next message's headers) and
        # _read_body (for the current message's body).
        self._pushback = b""
        # Handlers for server-to-client requests (DAP "reverse requests"),
        # e.g. vscode-js-debug's ``startDebugging``. See ``register_reverse_handler``.
        self._reverse_handlers: dict[str, ReverseHandler] = {}

    # ---- connection lifecycle ------------------------------------------------

    def connect(self, host: str, port: int, *, timeout: float = 5.0) -> None:
        sock = socket.create_connection((host, port), timeout=timeout)
        self.attach_socket(sock)

    def attach_socket(self, sock: socket.socket) -> None:
        """Take ownership of an already-connected socket and start the reader."""
        if self._sock is not None:
            raise RuntimeError("DapClient already connected")
        sock.settimeout(None)  # blocking recv in reader thread
        self._sock = sock
        self._closed.clear()
        self._reader = threading.Thread(target=self._read_loop, name="dap-reader", daemon=True)
        self._reader.start()

    def disconnect(self) -> None:
        if self._sock is None:
            return
        # Best-effort polite disconnect; ignore failures (peer may already be gone).
        with contextlib.suppress(DapError, OSError):
            self.request("disconnect", {"terminateDebuggee": False}, timeout=1.0)
        self._shutdown()

    def _shutdown(self) -> None:
        self._closed.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                sock.close()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=2.0)
        self._reader = None
        # Fail any pending requests.
        with self._pending_lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _, p in pending:
            p.success = False
            p.error = "connection closed"
            p.event.set()

    # ---- wire layer ----------------------------------------------------------

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def _send(self, msg: dict[str, Any]) -> None:
        sock = self._sock
        if sock is None:
            raise DapError(msg.get("command", "?"), "not connected")
        data = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        payload = header + data
        with self._send_lock:
            try:
                sock.sendall(payload)
            except OSError as e:
                raise DapError(msg.get("command", "?"), f"send failed: {e}") from e

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        chunks: list[bytes] = []
        remaining = n
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("socket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _recv_headers(self, sock: socket.socket) -> dict[str, str] | None:
        """Read header block ending in ``\\r\\n\\r\\n``. Returns None at EOF."""
        # Start with any bytes a previous _read_body left over — those bytes
        # belong to the NEXT message and may already contain its headers.
        buf = bytearray(self._pushback)
        self._pushback = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                if not buf:
                    return None
                raise ConnectionError("socket closed mid-header")
            buf.extend(chunk)
        header_bytes, _, rest = bytes(buf).partition(b"\r\n\r\n")
        # Anything past the header boundary belongs to this message's body.
        self._pushback = rest
        headers: dict[str, str] = {}
        for line in header_bytes.split(b"\r\n"):
            if not line:
                continue
            name, _, value = line.partition(b":")
            headers[name.decode("ascii").strip().lower()] = value.decode("ascii").strip()
        return headers

    def _read_body(self, sock: socket.socket, n: int) -> bytes:
        pushback = self._pushback
        if len(pushback) >= n:
            self._pushback = pushback[n:]
            return pushback[:n]
        self._pushback = b""
        return pushback + self._recv_exact(sock, n - len(pushback))

    def _read_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            while not self._closed.is_set():
                headers = self._recv_headers(sock)
                if headers is None:
                    break  # clean EOF
                length_str = headers.get("content-length")
                if length_str is None:
                    raise ConnectionError("missing Content-Length header")
                length = int(length_str)
                body = self._read_body(sock, length)
                msg = json.loads(body.decode("utf-8"))
                self._dispatch(msg)
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            # Reader noticed the connection is gone — make sure everyone else does too.
            if not self._closed.is_set():
                self._closed.set()
                with self._pending_lock:
                    pending = list(self._pending.items())
                    self._pending.clear()
                for _, p in pending:
                    p.success = False
                    p.error = "connection closed"
                    p.event.set()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "response":
            req_seq = int(msg.get("request_seq", 0))
            # Don't pop here — the waiting caller owns removal. Popping here
            # would race with wait_response()'s lookup and lose the result.
            with self._pending_lock:
                pending = self._pending.get(req_seq)
            if pending is not None:
                pending.success = bool(msg.get("success"))
                pending.body = msg.get("body") or {}
                pending.error = str(msg.get("message") or "")
                pending.event.set()
        elif mtype == "event":
            self._events.put(msg)
        elif mtype == "request":
            self._handle_reverse_request(msg)

    # ---- reverse requests (server → client) ---------------------------------

    def register_reverse_handler(self, command: str, handler: ReverseHandler) -> None:
        """Register a handler for a DAP reverse request (``type: "request"``).

        DAP allows the server to send requests to the client — used by
        vscode-js-debug to ask us to start a child session
        (``startDebugging``) and by some adapters for ``runInTerminal``.
        The handler runs on the reader thread, so it MUST be fast and
        non-blocking on this connection (opening a NEW socket is fine).
        """
        self._reverse_handlers[command] = handler

    def _handle_reverse_request(self, msg: dict[str, Any]) -> None:
        command = str(msg.get("command", ""))
        req_seq = int(msg.get("seq", 0))
        handler = self._reverse_handlers.get(command)
        if handler is None:
            # Politely tell the server we don't support this — DAP requires
            # SOME response or the server may stall waiting for one.
            self._send_response(req_seq, command, success=False, message="not supported")
            return
        try:
            body = handler(msg.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001 — reflect any handler failure to the peer
            self._send_response(
                req_seq, command, success=False, message=f"{type(exc).__name__}: {exc}"
            )
            return
        self._send_response(req_seq, command, success=True, body=body or {})

    def _send_response(
        self,
        request_seq: int,
        command: str,
        *,
        success: bool,
        body: dict[str, Any] | None = None,
        message: str = "",
    ) -> None:
        """Emit a DAP response frame for a server→client request we just handled."""
        resp: dict[str, Any] = {
            "type": "response",
            "seq": self._next_seq(),
            "request_seq": request_seq,
            "command": command,
            "success": success,
        }
        if body is not None:
            resp["body"] = body
        if message:
            resp["message"] = message
        with contextlib.suppress(DapError):
            self._send(resp)

    # ---- public API ----------------------------------------------------------

    def send_request(self, command: str, args: dict[str, Any] | None = None) -> int:
        """Send a request without waiting for a response. Returns the seq.

        Useful for DAP commands like ``launch`` whose response only arrives
        after ``configurationDone`` — pipelining is required.
        """
        if self._closed.is_set() or self._sock is None:
            raise DapError(command, "not connected")
        seq = self._next_seq()
        pending = _Pending()
        with self._pending_lock:
            self._pending[seq] = pending
        msg: dict[str, Any] = {"seq": seq, "type": "request", "command": command}
        if args is not None:
            msg["arguments"] = args
        try:
            self._send(msg)
        except DapError:
            with self._pending_lock:
                self._pending.pop(seq, None)
            raise
        return seq

    def wait_response(self, seq: int, command: str, *, timeout: float = 10.0) -> dict[str, Any]:
        """Block until the response for ``seq`` (issued via ``send_request``) arrives."""
        with self._pending_lock:
            pending = self._pending.get(seq)
        if pending is None:
            raise DapError(command, f"no pending request with seq={seq}")
        try:
            if not pending.event.wait(timeout):
                raise DapError(command, f"timed out after {timeout}s")
            if not pending.success:
                raise DapError(command, pending.error or "request failed")
            return pending.body
        finally:
            with self._pending_lock:
                self._pending.pop(seq, None)

    def request(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        seq = self.send_request(command, args)
        return self.wait_response(seq, command, timeout=timeout)

    # Convenience wrappers — each returns the response body.

    def initialize(self, *, adapter_id: str = "debug-agent") -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "clientID": "debug-agent",
                "clientName": "debug-agent",
                "adapterID": adapter_id,
                "locale": "en-US",
                "linesStartAt1": True,
                "columnsStartAt1": True,
                "pathFormat": "path",
                "supportsRunInTerminalRequest": False,
                "supportsVariableType": True,
            },
        )

    def launch(
        self,
        program: Path,
        *,
        args: list[str] | None = None,
        cwd: Path | None = None,
        stop_on_entry: bool = False,
        console: str = "internalConsole",
    ) -> dict[str, Any]:
        """Send a ``launch`` request and BLOCK for the response.

        Per DAP spec the launch response only arrives after
        ``configurationDone``. If you intend to set breakpoints first,
        use ``send_request('launch', ...)`` + ``wait_for_event('initialized')``
        and call ``wait_response(seq, 'launch')`` after configurationDone.
        """
        payload: dict[str, Any] = {
            "type": "python",
            "request": "launch",
            "program": str(program),
            "stopOnEntry": stop_on_entry,
            "console": console,
        }
        if args is not None:
            payload["args"] = args
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return self.request("launch", payload)

    def attach(self, *, host: str, port: int) -> dict[str, Any]:
        """Send an ``attach`` request and BLOCK for the response.

        Same DAP-pipelining caveat as :meth:`launch` — use the explicit
        ``send_request`` / ``wait_response`` split if you need to interleave
        configuration before the response arrives.
        """
        return self.request(
            "attach",
            {"connect": {"host": host, "port": port}},
        )

    def set_breakpoints(
        self,
        source: Path,
        bps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.request(
            "setBreakpoints",
            {
                "source": {"path": str(source), "name": source.name},
                "breakpoints": bps,
                "lines": [bp["line"] for bp in bps if "line" in bp],
            },
        )

    def set_exception_breakpoints(self, filters: list[str]) -> dict[str, Any]:
        return self.request("setExceptionBreakpoints", {"filters": filters})

    def configuration_done(self) -> dict[str, Any]:
        return self.request("configurationDone", {})

    def continue_(self, thread_id: int) -> dict[str, Any]:
        return self.request("continue", {"threadId": thread_id})

    def next(self, thread_id: int) -> dict[str, Any]:
        return self.request("next", {"threadId": thread_id})

    def step_in(self, thread_id: int) -> dict[str, Any]:
        return self.request("stepIn", {"threadId": thread_id})

    def step_out(self, thread_id: int) -> dict[str, Any]:
        return self.request("stepOut", {"threadId": thread_id})

    def pause(self, thread_id: int) -> dict[str, Any]:
        return self.request("pause", {"threadId": thread_id})

    def stack_trace(self, thread_id: int, *, levels: int = 20) -> dict[str, Any]:
        return self.request(
            "stackTrace",
            {"threadId": thread_id, "startFrame": 0, "levels": levels},
        )

    def scopes(self, frame_id: int) -> dict[str, Any]:
        return self.request("scopes", {"frameId": frame_id})

    def variables(self, variables_reference: int) -> dict[str, Any]:
        return self.request("variables", {"variablesReference": variables_reference})

    def evaluate(
        self,
        expression: str,
        *,
        frame_id: int | None = None,
        context: str = "repl",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"expression": expression, "context": context}
        if frame_id is not None:
            payload["frameId"] = frame_id
        return self.request("evaluate", payload)

    def threads(self) -> dict[str, Any]:
        return self.request("threads", {})

    def terminate(self) -> dict[str, Any]:
        return self.request("terminate", {})

    # ---- events --------------------------------------------------------------

    def poll_event(self, *, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            if timeout is None:
                return self._events.get_nowait()
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for_event(self, event_name: str, *, timeout: float = 10.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        # Replay anything we already received but don't drop unrelated events
        # other callers may want; instead we re-queue them at the end.
        skipped: list[dict[str, Any]] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DapError("wait_for_event", f"timed out waiting for {event_name!r}")
                try:
                    msg = self._events.get(timeout=remaining)
                except queue.Empty as e:
                    raise DapError("wait_for_event", f"timed out waiting for {event_name!r}") from e
                if msg.get("event") == event_name:
                    return msg
                skipped.append(msg)
        finally:
            for m in skipped:
                self._events.put(m)
