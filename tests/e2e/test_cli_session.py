from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple_ok.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.e2e
def test_session_start_inspect_release(tmp_path: Path) -> None:
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text())

    start = _cli(
        "session",
        "start",
        str(target),
        "--break-at",
        f"{target}:3",
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    ctx = json.loads(start.stdout)
    assert ctx["status"] == "stopped"
    assert ctx["location"]["line"] == 3

    inspect = _cli("session", "inspect", cwd=tmp_path)
    assert inspect.returncode == 0, inspect.stderr
    ctx2 = json.loads(inspect.stdout)
    assert ctx2["status"] == "stopped"
    assert ctx2["location"]["line"] == 3

    # inspect should be safe to call multiple times in a row.
    inspect2 = _cli("session", "inspect", cwd=tmp_path)
    assert inspect2.returncode == 0, inspect2.stderr
    ctx3 = json.loads(inspect2.stdout)
    assert ctx3["status"] == "stopped"

    release = _cli("session", "release", cwd=tmp_path)
    assert release.returncode == 0, release.stderr
    payload = json.loads(release.stdout)
    assert payload["status"] == "ok"

    sessions_root = tmp_path / ".debug-agent" / "sessions"
    assert not (sessions_root / "default").exists()


@pytest.mark.e2e
def test_session_release_idempotent(tmp_path: Path) -> None:
    release = _cli("session", "release", cwd=tmp_path)
    assert release.returncode == 0
    payload = json.loads(release.stdout)
    assert payload["status"] == "ok"


@pytest.mark.e2e
def test_session_stop_alias(tmp_path: Path) -> None:
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text())
    start = _cli("session", "start", str(target), "--break-at", f"{target}:3", cwd=tmp_path)
    assert start.returncode == 0, start.stderr
    stop = _cli("session", "stop", cwd=tmp_path)
    assert stop.returncode == 0, stop.stderr
    payload = json.loads(stop.stdout)
    assert payload["status"] == "ok"


@pytest.mark.e2e
def test_session_start_then_immediate_release_no_orphans(tmp_path: Path) -> None:
    """Stress: start+release rapidly several times, ensure clean teardown each time."""
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text())
    for _ in range(3):
        start = _cli(
            "session",
            "start",
            str(target),
            "--break-at",
            f"{target}:3",
            cwd=tmp_path,
        )
        assert start.returncode == 0, start.stderr
        release = _cli("session", "release", cwd=tmp_path)
        assert release.returncode == 0, release.stderr
    sessions_root = tmp_path / ".debug-agent" / "sessions"
    assert not (sessions_root / "default").exists()


@pytest.mark.e2e
def test_session_start_replaces_stale_meta(tmp_path: Path) -> None:
    """A meta.json with a dead PID should be cleaned up automatically on next start."""
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text())
    sessions_root = tmp_path / ".debug-agent" / "sessions" / "default"
    sessions_root.mkdir(parents=True, exist_ok=True)
    # Plant a meta.json pointing at a definitely-dead PID.
    (sessions_root / "meta.json").write_text(
        json.dumps(
            {
                "session_id": "default",
                "pid": 999999,
                "control_port": 1,
                "status": "stopped",
            }
        ),
        encoding="utf-8",
    )

    start = _cli(
        "session",
        "start",
        str(target),
        "--break-at",
        f"{target}:3",
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    ctx = json.loads(start.stdout)
    assert ctx["status"] == "stopped"

    release = _cli("session", "release", cwd=tmp_path)
    assert release.returncode == 0, release.stderr
