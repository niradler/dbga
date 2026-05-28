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


def _release_all(tmp_path: Path, names: list[str]) -> None:
    for name in names:
        _cli("session", "release", "--session", name, cwd=tmp_path)


@pytest.mark.e2e
def test_sessions_ls_empty(tmp_path: Path) -> None:
    r = _cli("sessions", "ls", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload == {"sessions": [], "cleaned": []}


@pytest.mark.e2e
def test_sessions_ls_lists_single_session(tmp_path: Path) -> None:
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text())
    start = _cli("session", "start", str(target), "--break-at", f"{target}:3", cwd=tmp_path)
    assert start.returncode == 0, start.stderr
    try:
        r = _cli("sessions", "ls", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["cleaned"] == []
        assert len(payload["sessions"]) == 1
        entry = payload["sessions"][0]
        assert entry["name"] == "default"
        assert isinstance(entry["pid"], int)
        assert entry["script"] == str(target.resolve())
        assert entry["status"] in {"stopped", "running", "starting"}
    finally:
        _release_all(tmp_path, ["default"])


@pytest.mark.e2e
def test_sessions_ls_lists_multiple_named(tmp_path: Path) -> None:
    target = tmp_path / "simple_ok.py"
    target.write_text(FIXTURE.read_text())
    a = _cli(
        "session", "start", "--session", "a", str(target), "--break-at", f"{target}:3", cwd=tmp_path
    )
    assert a.returncode == 0, a.stderr
    b = _cli(
        "session", "start", "--session", "b", str(target), "--break-at", f"{target}:3", cwd=tmp_path
    )
    assert b.returncode == 0, b.stderr
    try:
        r = _cli("sessions", "ls", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        names = sorted(s["name"] for s in payload["sessions"])
        assert names == ["a", "b"]
        assert payload["cleaned"] == []
    finally:
        _release_all(tmp_path, ["a", "b"])


@pytest.mark.e2e
def test_sessions_ls_cleans_zombie(tmp_path: Path) -> None:
    sessions_root = tmp_path / ".debug-agent" / "sessions" / "ghost"
    sessions_root.mkdir(parents=True, exist_ok=True)
    (sessions_root / "meta.json").write_text(
        json.dumps({"session_id": "ghost", "pid": 999999, "control_port": 1, "status": "stopped"}),
        encoding="utf-8",
    )
    r = _cli("sessions", "ls", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["sessions"] == []
    assert len(payload["cleaned"]) == 1
    assert payload["cleaned"][0]["name"] == "ghost"
    assert payload["cleaned"][0]["removed_zombie"] is True
    # The directory should be gone.
    assert not sessions_root.exists()
