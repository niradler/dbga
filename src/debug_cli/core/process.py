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
        _kill_tree(proc.pid)
        stdout, stderr = proc.communicate()
    duration_ms = int((time.monotonic() - start) * 1000)
    return RunResult(
        exit_code=proc.returncode,
        duration_ms=duration_ms,
        timed_out=timed_out,
        stdout=stdout or "",
        stderr=stderr or "",
        killed_signal="SIGTERM" if timed_out else None,
    )


def _creation_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined,unused-ignore]
    return 0


def _kill_tree(pid: int) -> None:
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
