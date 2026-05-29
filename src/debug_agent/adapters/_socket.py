"""Generic TCP helpers shared by all DAP-adapter subprocess shims.

Both ``debugpy.adapter`` and ``dlv dap`` (and any other DAP server we wrap)
need the same boot dance: bind an ephemeral port, spawn the adapter on it,
then connect once the adapter is accepting.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time


def find_free_port() -> int:
    """Bind to an ephemeral port and return it (released on close)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_until_listening(
    port: int,
    *,
    host: str = "127.0.0.1",
    timeout: float = 5.0,
    proc: subprocess.Popen[bytes] | None = None,
    adapter_label: str = "DAP adapter",
) -> socket.socket:
    """Block until ``host:port`` accepts a TCP connection, return that socket.

    Many DAP adapters (``debugpy.adapter`` is one) accept exactly one client
    — probe-and-close would cause them to exit. So this returns the live
    socket on success; the caller should hand it to the DAP client.

    If ``proc`` is supplied, we abort early when the adapter subprocess exits
    before the port is accepting connections — surfaces "adapter crashed on
    startup" as itself rather than a generic timeout.
    """
    deadline = time.monotonic() + timeout
    last_err: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection((host, port), timeout=0.5)
        except OSError as e:
            last_err = e
        if proc is not None and proc.poll() is not None:
            stderr = b""
            if proc.stderr is not None:
                with contextlib.suppress(OSError):
                    stderr = proc.stderr.read() or b""
            raise RuntimeError(
                f"{adapter_label} exited with code {proc.returncode} "
                f"before listening on {host}:{port}: "
                f"{stderr.decode(errors='replace')[:500]}"
            )
        time.sleep(0.05)
    raise TimeoutError(
        f"{adapter_label} not reachable on {host}:{port} within {timeout}s (last error: {last_err})"
    )
