"""Integration test: the daemon's watchdog tears itself down on idle.

The daemon does NOT remove its own session directory on idle exit — that's
intentional: ``sessions ls`` is the consumer that reaps zombie directories
on the next run. We assert here that the PID dies; cleanup of the directory
is exercised by ``test_cli_sessions_ls.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from debug_cli.core.state import is_pid_alive

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple_ok.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.integration
def test_idle_timeout_kills_daemon(tmp_path: Path) -> None:
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")
    start = _cli(
        "session",
        "start",
        "--idle-timeout",
        "2",
        str(target),
        "--break-at",
        f"{target}:3",
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr

    meta = json.loads(
        (tmp_path / ".debug-cli" / "sessions" / "default" / "meta.json").read_text("utf-8")
    )
    pid = int(meta["pid"])
    assert is_pid_alive(pid)

    # Watchdog wakes every idle_timeout/4 — give it ample slack to fire.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            break
        time.sleep(0.25)
    assert not is_pid_alive(pid), f"daemon pid {pid} still alive after idle timeout"

    # Whether the directory is gone or marked terminated is acceptable.
    sdir = tmp_path / ".debug-cli" / "sessions" / "default"
    if sdir.exists():
        # Reap it via ``sessions ls`` so subsequent runs are clean.
        ls = _cli("sessions", "ls", cwd=tmp_path)
        assert ls.returncode == 0, ls.stderr
        payload = json.loads(ls.stdout)
        cleaned_names = {c["name"] for c in payload["cleaned"]}
        assert "default" in cleaned_names or not sdir.exists()
