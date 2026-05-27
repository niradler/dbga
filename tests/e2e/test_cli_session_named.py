from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple_ok.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.e2e
def test_named_sessions_are_independent(tmp_path: Path) -> None:
    """Two named sessions can run side-by-side without colliding."""
    target_a = tmp_path / "a.py"
    target_b = tmp_path / "b.py"
    target_a.write_text(FIXTURE.read_text(), encoding="utf-8")
    target_b.write_text(FIXTURE.read_text(), encoding="utf-8")

    a = _cli(
        "session",
        "start",
        "--session",
        "alpha",
        str(target_a),
        "--break-at",
        f"{target_a}:2",
        cwd=tmp_path,
    )
    assert a.returncode == 0, a.stderr
    b = _cli(
        "session",
        "start",
        "--session",
        "beta",
        str(target_b),
        "--break-at",
        f"{target_b}:3",
        cwd=tmp_path,
    )
    assert b.returncode == 0, b.stderr
    try:
        ia = _cli("session", "inspect", "--session", "alpha", cwd=tmp_path)
        assert ia.returncode == 0, ia.stderr
        ctx_a = json.loads(ia.stdout)
        assert ctx_a["session_id"] == "alpha"
        assert ctx_a["location"]["line"] == 2

        ib = _cli("session", "inspect", "--session", "beta", cwd=tmp_path)
        assert ib.returncode == 0, ib.stderr
        ctx_b = json.loads(ib.stdout)
        assert ctx_b["session_id"] == "beta"
        assert ctx_b["location"]["line"] == 3
    finally:
        _cli("session", "release", "--session", "alpha", cwd=tmp_path)
        _cli("session", "release", "--session", "beta", cwd=tmp_path)
