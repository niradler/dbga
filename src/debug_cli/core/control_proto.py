"""Length-prefixed JSON framing for the localhost session control socket.

Wire format: ``[4-byte big-endian length][UTF-8 JSON body]``. One request
yields one response; no events; no pipelining. Both the CLI client and the
``session_proc`` daemon use the helpers here.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

_LENGTH_PREFIX = struct.Struct(">I")
_MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # 64 MiB cap; refuse anything larger


def send(sock: socket.socket, obj: dict[str, Any]) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sock.sendall(_LENGTH_PREFIX.pack(len(data)) + data)


def _recv_exactly(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def recv(sock: socket.socket) -> dict[str, Any] | None:
    """Read one framed JSON message. Returns ``None`` on clean EOF or any
    malformed input (bad length, truncated body, invalid UTF-8, non-dict)."""
    header = _recv_exactly(sock, _LENGTH_PREFIX.size)
    if header is None:
        return None
    (length,) = _LENGTH_PREFIX.unpack(header)
    if length <= 0 or length > _MAX_MESSAGE_BYTES:
        return None
    body = _recv_exactly(sock, length)
    if body is None:
        return None
    try:
        text = body.decode("utf-8")
        parsed = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
