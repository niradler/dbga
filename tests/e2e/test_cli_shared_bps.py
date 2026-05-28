from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _copy(name: str, tmp_path: Path) -> Path:
    target = tmp_path / name
    shutil.copyfile(FIXTURES / name, target)
    return target


def _release(tmp_path: Path) -> None:
    _cli("session", "release", cwd=tmp_path, timeout=30.0)


def _write_shared_bps(tmp_path: Path, entries: list[dict]) -> Path:
    state = tmp_path / ".debug-agent"
    state.mkdir(parents=True, exist_ok=True)
    bps = state / "breakpoints.json"
    bps.write_text(json.dumps(entries), encoding="utf-8")
    return bps


def _read_shared_bps(tmp_path: Path) -> list[dict]:
    bps = tmp_path / ".debug-agent" / "breakpoints.json"
    if not bps.exists():
        return []
    return json.loads(bps.read_text(encoding="utf-8"))


@pytest.mark.e2e
def test_use_bps_file_applies_initial_breakpoints(tmp_path: Path) -> None:
    target = _copy("stepping_fixture.py", tmp_path)
    _write_shared_bps(
        tmp_path,
        [{"file": str(target), "line": 9, "condition": None}],
    )
    try:
        # Start with --use-bps-file but NO --break-at; the bp should come
        # entirely from the shared file. We also pass stop-on-entry so the
        # initial stop is reproducible regardless of where the bp lands.
        start = _cli(
            "session",
            "start",
            "--use-bps-file",
            "--stop-on-entry",
            str(target),
            cwd=tmp_path,
        )
        assert start.returncode == 0, start.stdout + start.stderr

        ls = _cli("session", "list-bp", cwd=tmp_path)
        listed = json.loads(ls.stdout)
        assert any(b["line"] == 9 for b in listed["breakpoints"])

        # Continue — the script should stop at the shared bp on line 9.
        cont = _cli("session", "continue", cwd=tmp_path)
        ctx = json.loads(cont.stdout)
        assert ctx["status"] == "stopped"
        assert ctx["location"]["line"] == 9
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_set_bp_writes_to_shared_file(tmp_path: Path) -> None:
    target = _copy("stepping_fixture.py", tmp_path)
    try:
        start = _cli(
            "session",
            "start",
            "--break-at",
            f"{target}:7",
            str(target),
            cwd=tmp_path,
        )
        assert start.returncode == 0, start.stdout + start.stderr

        s = _cli("session", "set-bp", f"{target}:9", cwd=tmp_path)
        assert s.returncode == 0, s.stderr

        shared = _read_shared_bps(tmp_path)
        assert any(Path(b["file"]) == target.resolve() and b["line"] == 9 for b in shared), shared

        # Clearing the bp should also remove it from the shared file.
        c = _cli("session", "clear-bp", f"{target}:9", cwd=tmp_path)
        assert c.returncode == 0, c.stderr
        shared2 = _read_shared_bps(tmp_path)
        assert not any(b["line"] == 9 for b in shared2), shared2
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_no_write_bps_file_skips_shared_write(tmp_path: Path) -> None:
    target = _copy("stepping_fixture.py", tmp_path)
    try:
        start = _cli(
            "session",
            "start",
            "--break-at",
            f"{target}:7",
            "--no-write-bps-file",
            str(target),
            cwd=tmp_path,
        )
        assert start.returncode == 0, start.stdout + start.stderr

        s = _cli("session", "set-bp", f"{target}:9", cwd=tmp_path)
        assert s.returncode == 0, s.stderr

        # The shared file should remain the empty list created by ensure_state_dir.
        shared = _read_shared_bps(tmp_path)
        assert shared == [], shared
    finally:
        _release(tmp_path)
