from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "stepping_fixture.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.e2e
def test_set_bp_response_includes_warnings_field(tmp_path: Path) -> None:
    """``set-bp`` response always carries a ``warnings`` array (even if empty)."""
    target = tmp_path / "stepping_fixture.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")
    start = _cli("session", "start", str(target), "--break-at", f"{target}:7", cwd=tmp_path)
    assert start.returncode == 0, start.stderr
    try:
        r = _cli("session", "set-bp", f"{target}:9", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert "warnings" in payload
        assert isinstance(payload["warnings"], list)
    finally:
        _cli("session", "release", cwd=tmp_path)


@pytest.mark.e2e
def test_set_bp_on_blank_line_warns_or_adjusts(tmp_path: Path) -> None:
    """A bp on a blank line should either warn (unresolved) or warn (adjusted)."""
    target = tmp_path / "stepping_fixture.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")
    start = _cli("session", "start", str(target), "--break-at", f"{target}:7", cwd=tmp_path)
    assert start.returncode == 0, start.stderr
    try:
        # Line 4 of the fixture is a blank line between functions.
        r = _cli("session", "set-bp", f"{target}:4", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        # debugpy may either reject it (unresolved) or shift to the next code
        # line (adjusted). Either way, a warning must surface.
        assert payload["warnings"], f"expected a warning for bp on blank line; got {payload!r}"
        msg = payload["warnings"][0]
        assert "unresolved" in msg or "adjusted" in msg
    finally:
        _cli("session", "release", cwd=tmp_path)
