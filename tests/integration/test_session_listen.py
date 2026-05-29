from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from debug_agent.core.state import is_pid_alive

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _cli(*args: str, cwd: Path, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
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
        # Don't re-probe the port here: ``_spawn_listen_mode`` already gates
        # ``status: listening`` on the port accepting (it waits up to 10s), so
        # a second connect is redundant — and racy, because debugpy
        # ``--wait-for-client`` accepts a single client and a throwaway TCP
        # probe can perturb the listener (the source of an intermittent CI
        # failure). Assert the listener process is alive instead; that plus the
        # contract fields above verifies a usable attach endpoint was returned.
        assert is_pid_alive(proc_pid)
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
