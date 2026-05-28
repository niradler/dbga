from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    exit_code: int
    duration_ms: int
    timed_out: bool
    stdout: str
    stderr: str
    killed_signal: str | None = None


def run_with_timeout(
    cmd: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> RunResult:
    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_creation_flags(),
        start_new_session=(sys.platform != "win32"),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        stdout, stderr = proc.communicate()
    duration_ms = int((time.monotonic() - start) * 1000)
    killed_signal: str | None = None
    if timed_out:
        killed_signal = "TASKKILL" if sys.platform == "win32" else "SIGTERM"
    return RunResult(
        exit_code=proc.returncode,
        duration_ms=duration_ms,
        timed_out=timed_out,
        stdout=stdout or "",
        stderr=stderr or "",
        killed_signal=killed_signal,
    )


def windows_no_window_flags() -> int:
    """Creation flags that prevent a console window from flashing on Windows.

    ``CREATE_NO_WINDOW`` keeps the child running as a console application but
    without allocating a visible console, which matters when the parent is
    itself windowless (e.g. a detached daemon) and would otherwise cause
    Windows to allocate a fresh console for the child.
    """
    if sys.platform == "win32":
        return 0x08000000  # CREATE_NO_WINDOW
    return 0


def _creation_flags() -> int:
    return windows_no_window_flags()


def kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=5,
        )
    else:
        import os
        import signal

        try:  # noqa: SIM105 - keep explicit try/except to avoid extra import inside POSIX branch
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
