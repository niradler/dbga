from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "loop_fixture.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.e2e
def test_conditional_break_at_on_start(tmp_path: Path) -> None:
    target = tmp_path / "loop_fixture.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")

    # Stop only on iteration i == 5 — verifies --break-at supports a condition.
    start = _cli(
        "session",
        "start",
        str(target),
        "--break-at",
        f"{target}:4:i == 5",
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    payload = json.loads(start.stdout)
    assert payload["status"] == "stopped", payload
    locals_by_name = {v["name"]: v for v in payload["locals"]}
    assert locals_by_name["i"]["value"] == "5"

    _cli("session", "release", cwd=tmp_path)
