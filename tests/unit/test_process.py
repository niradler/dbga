from __future__ import annotations

import sys
from pathlib import Path

from debug_agent.core.process import RunResult, run_with_timeout


def test_run_captures_stdout() -> None:
    result = run_with_timeout([sys.executable, "-c", "print('hello')"], timeout=5.0)
    assert isinstance(result, RunResult)
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "hello" in result.stdout


def test_timeout_kills_child_processes() -> None:
    fixture = Path(__file__).parent.parent / "fixtures" / "sleep_with_child.py"
    result = run_with_timeout([sys.executable, str(fixture)], timeout=2.0)
    assert result.timed_out is True
    assert result.duration_ms < 5000


def test_killed_signal_reflects_platform() -> None:
    """Windows uses taskkill; POSIX uses SIGTERM. Track the actual signal."""
    fixture = Path(__file__).parent.parent / "fixtures" / "sleep_with_child.py"
    result = run_with_timeout([sys.executable, str(fixture)], timeout=2.0)
    assert result.timed_out is True
    expected = "TASKKILL" if sys.platform == "win32" else "SIGTERM"
    assert result.killed_signal == expected


def test_killed_signal_is_none_when_not_timed_out() -> None:
    result = run_with_timeout([sys.executable, "-c", "print('ok')"], timeout=5.0)
    assert result.timed_out is False
    assert result.killed_signal is None
