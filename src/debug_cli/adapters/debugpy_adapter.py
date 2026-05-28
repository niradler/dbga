"""Helpers for spawning the debugpy DAP adapter and connecting to it.

Architectural note: we use the **standalone adapter** pattern (the same
one VS Code uses). We spawn ``python -m debugpy.adapter --host 127.0.0.1
--port <port>`` as its own subprocess. The adapter listens for one DAP
client, and we then drive a normal ``initialize`` / ``launch`` sequence
through it. The adapter takes care of spawning the actual debuggee.

We tried the simpler "single-step" pattern (``python -m debugpy --listen
:<port> --wait-for-client <script>``) first, but in debugpy 1.8.20 that
mode delegates to an internal adapter that never gets spawned in our
environment — it hangs forever on ``Waiting for adapter endpoints...``.
The standalone adapter pattern is reliable and well documented.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
import time


def find_free_port() -> int:
    """Bind to an ephemeral port and return it (released on close)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def spawn_adapter(port: int, *, host: str = "127.0.0.1") -> subprocess.Popen[bytes]:
    """Spawn ``debugpy.adapter`` in debugServer mode on ``host:port``."""
    return subprocess.Popen(
        [sys.executable, "-m", "debugpy.adapter", "--host", host, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def wait_until_listening(
    port: int,
    *,
    host: str = "127.0.0.1",
    timeout: float = 5.0,
    proc: subprocess.Popen[bytes] | None = None,
) -> socket.socket:
    """Block until ``host:port`` accepts a TCP connection, return that socket.

    ``debugpy.adapter`` only accepts a single client connection — if we
    probe-and-close, the adapter exits. So this returns the live socket
    on success, which the caller should hand to the DAP client.

    If ``proc`` is supplied, we abort early if the adapter subprocess exits
    before the port is accepting connections — surfaces "adapter crashed
    on startup" as itself rather than as a generic timeout.
    """
    deadline = time.monotonic() + timeout
    last_err: OSError | None = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            stderr = b""
            if proc.stderr is not None:
                with contextlib.suppress(OSError):
                    stderr = proc.stderr.read() or b""
            raise RuntimeError(
                f"debugpy adapter exited with code {proc.returncode} "
                f"before listening on {host}:{port}: {stderr.decode(errors='replace')[:500]}"
            )
        try:
            return socket.create_connection((host, port), timeout=0.5)
        except OSError as e:
            last_err = e
            time.sleep(0.05)
    raise TimeoutError(
        f"debugpy adapter not reachable on {host}:{port} within {timeout}s (last error: {last_err})"
    )
