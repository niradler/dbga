from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _port_listening(host: str, port: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _cli(*args: str, cwd: Path, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.integration
def test_session_start_listen_returns_attach_url(tmp_path: Path) -> None:
    target = tmp_path / "simple_ok.py"
    shutil.copyfile(FIXTURES / "simple_ok.py", target)
    port = _free_port()
    proc_pid: int | None = None
    try:
        r = _cli(
            "session",
            "start",
            "--listen",
            str(port),
            "--session",
            "listen_test",
            str(target),
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        payload = json.loads(r.stdout)
        assert payload["status"] == "listening"
        assert payload["attach_url"] == f"debugpy://127.0.0.1:{port}"
        assert payload["port"] == port
        proc_pid = int(payload["pid"])
        # The CLI returns ``status: listening`` only once the port is actually
        # accepting connections — verify the contract by reconnecting. Empty
        # TCP probes don't consume debugpy's single-client slot (it's looking
        # for a DAP handshake), so this is safe to do.
        assert _port_listening("127.0.0.1", port, timeout=5.0)
    finally:
        if proc_pid:
            # In listen mode there's no daemon to ``session release`` against —
            # the debuggee is the listener itself. Kill it directly.
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc_pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                import os
                import signal

                with contextlib.suppress(ProcessLookupError):
                    os.kill(proc_pid, signal.SIGTERM)
