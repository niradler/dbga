"""Unit tests for DAP server-to-client (reverse) request handling.

The DAP spec allows the server to send ``type: "request"`` messages to
the client (``startDebugging``, ``runInTerminal``). DapClient routes
these to handlers registered via ``register_reverse_handler`` and sends
a matching response back over the same connection.

We exercise the routing in isolation by feeding DAP frames into a pair
of socket halves — no real debugger, no subprocess.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any

from debug_agent.core.dap_client import DapClient


def _frame(msg: dict[str, Any]) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_frame(sock: socket.socket, *, timeout: float = 2.0) -> dict[str, Any]:
    sock.settimeout(timeout)
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    header, _, rest = buf.partition(b"\r\n\r\n")
    length = 0
    for line in header.split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.decode().strip().lower() == "content-length":
            length = int(value.decode().strip())
    body = rest
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            raise ConnectionError("peer closed mid-body")
        body += chunk
    return json.loads(body.decode("utf-8"))


def _socket_pair() -> tuple[socket.socket, socket.socket]:
    """Listen + connect + accept on localhost to get a connected pair."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    client_sock: list[socket.socket] = []
    server_sock: list[socket.socket] = []

    def _accept() -> None:
        s, _ = listener.accept()
        server_sock.append(s)

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    c = socket.create_connection(("127.0.0.1", port))
    client_sock.append(c)
    t.join(timeout=2.0)
    listener.close()
    assert server_sock, "accept never fired"
    return client_sock[0], server_sock[0]


def test_unknown_reverse_request_gets_not_supported_response() -> None:
    """No registered handler → server should still get a 'success: false' response."""
    client_sock, server_sock = _socket_pair()
    client = DapClient()
    client.attach_socket(client_sock)
    try:
        # Simulate the server sending us a reverse request with no handler registered.
        server_sock.sendall(
            _frame(
                {
                    "type": "request",
                    "seq": 42,
                    "command": "runInTerminal",
                    "arguments": {"args": ["true"]},
                }
            )
        )
        resp = _read_frame(server_sock)
        assert resp["type"] == "response"
        assert resp["request_seq"] == 42
        assert resp["command"] == "runInTerminal"
        assert resp["success"] is False
    finally:
        client._shutdown()
        server_sock.close()


def test_reverse_request_handler_response_body() -> None:
    """Registered handler's return value lands in the response body."""
    client_sock, server_sock = _socket_pair()
    client = DapClient()
    client.attach_socket(client_sock)

    received_args: list[dict[str, Any]] = []

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        received_args.append(args)
        return {"sessionId": "child-1"}

    client.register_reverse_handler("startDebugging", handler)
    try:
        server_sock.sendall(
            _frame(
                {
                    "type": "request",
                    "seq": 7,
                    "command": "startDebugging",
                    "arguments": {"configuration": {"foo": "bar"}, "request": "launch"},
                }
            )
        )
        resp = _read_frame(server_sock)
        assert resp["type"] == "response"
        assert resp["request_seq"] == 7
        assert resp["command"] == "startDebugging"
        assert resp["success"] is True
        assert resp["body"] == {"sessionId": "child-1"}
        assert received_args == [{"configuration": {"foo": "bar"}, "request": "launch"}]
    finally:
        client._shutdown()
        server_sock.close()


def test_reverse_request_handler_exception_returns_failure() -> None:
    """A handler that raises must surface as ``success: false`` with the error message."""
    client_sock, server_sock = _socket_pair()
    client = DapClient()
    client.attach_socket(client_sock)

    def handler(_args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("child spawn failed")

    client.register_reverse_handler("startDebugging", handler)
    try:
        server_sock.sendall(
            _frame(
                {
                    "type": "request",
                    "seq": 11,
                    "command": "startDebugging",
                    "arguments": {},
                }
            )
        )
        resp = _read_frame(server_sock)
        assert resp["success"] is False
        assert "child spawn failed" in resp.get("message", "")
    finally:
        client._shutdown()
        server_sock.close()


def test_response_seq_is_distinct_from_request_seq() -> None:
    """The response frame's own ``seq`` must NOT collide with the request_seq."""
    client_sock, server_sock = _socket_pair()
    client = DapClient()
    client.attach_socket(client_sock)
    client.register_reverse_handler("startDebugging", lambda _a: None)
    try:
        server_sock.sendall(
            _frame(
                {
                    "type": "request",
                    "seq": 99,
                    "command": "startDebugging",
                    "arguments": {},
                }
            )
        )
        resp = _read_frame(server_sock)
        # request_seq echoes the SERVER's seq=99; our own seq must be from
        # our own counter (which started at 0 in the constructor).
        assert resp["request_seq"] == 99
        assert isinstance(resp["seq"], int)
        assert resp["seq"] != 99
    finally:
        client._shutdown()
        server_sock.close()
