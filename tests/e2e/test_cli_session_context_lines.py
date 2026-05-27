from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "stepping_fixture.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.e2e
def test_start_context_lines_one(tmp_path: Path) -> None:
    """--context-lines 1 → expect 1 before + current + 1 after = 3 entries."""
    target = tmp_path / "stepping_fixture.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")
    start = _cli(
        "session",
        "start",
        "--context-lines",
        "1",
        "--break-at",
        f"{target}:7",
        str(target),
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    try:
        ctx = json.loads(start.stdout)
        # The fixture's line 7 is well-inside the file; window should fit.
        assert len(ctx["source"]) == 3
        lines = [s["line"] for s in ctx["source"]]
        assert lines == [6, 7, 8]
    finally:
        _cli("session", "release", cwd=tmp_path)


@pytest.mark.e2e
def test_inspect_overrides_context_lines(tmp_path: Path) -> None:
    """--context-lines on ``inspect`` should override the session default."""
    target = tmp_path / "stepping_fixture.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")
    start = _cli(
        "session",
        "start",
        "--context-lines",
        "1",
        "--break-at",
        f"{target}:7",
        str(target),
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    try:
        r = _cli("session", "inspect", "--context-lines", "3", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)
        # 3 before + current + 3 after = 7 lines (file has enough surrounding).
        assert len(ctx["source"]) == 7
    finally:
        _cli("session", "release", cwd=tmp_path)
