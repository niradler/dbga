from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _cli(*args: str, cwd: Path, timeout: float = 90.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copyfile(FIXTURES / name, target)
    return target


def _release(tmp_path: Path, session: str = "default") -> None:
    _cli("session", "release", "--session", session, cwd=tmp_path, timeout=30.0)


@pytest.mark.e2e
def test_diagnose_crash_reruns_into_session(tmp_path: Path) -> None:
    target = _copy_fixture(tmp_path, "zerodiv.py")
    try:
        r = _cli(
            "diagnose",
            "--session",
            "diag",
            "--",
            sys.executable,
            str(target),
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        payload = json.loads(r.stdout)
        assert payload["status"] == "diagnosed"
        assert payload["traceback"]["error_type"] == "ZeroDivisionError"
        ctx = payload["session_context"]
        assert ctx["status"] == "stopped"
        # The deepest user frame is line 2 (``return a / b``).
        assert ctx["location"]["line"] == 2
        assert ctx["location"]["file"].endswith("zerodiv.py")
    finally:
        _release(tmp_path, "diag")


@pytest.mark.e2e
def test_diagnose_no_crash(tmp_path: Path) -> None:
    target = _copy_fixture(tmp_path, "simple_ok.py")
    r = _cli(
        "diagnose",
        "--session",
        "diag_ok",
        "--",
        sys.executable,
        str(target),
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == "no_crash"
    assert payload["exit_code"] == 0


@pytest.mark.e2e
def test_diagnose_no_rerun_returns_crash(tmp_path: Path) -> None:
    target = _copy_fixture(tmp_path, "zerodiv.py")
    r = _cli(
        "diagnose",
        "--no-rerun",
        "--session",
        "diag_nr",
        "--",
        sys.executable,
        str(target),
        cwd=tmp_path,
    )
    assert r.returncode == 1
    payload = json.loads(r.stdout)
    assert payload["status"] == "crash"
    assert payload["traceback"]["error_type"] == "ZeroDivisionError"
    # No session should have been spawned — releasing should be a no-op.
    rel = _cli("session", "release", "--session", "diag_nr", cwd=tmp_path, timeout=10.0)
    rel_payload = json.loads(rel.stdout)
    assert rel_payload.get("message") == "no session"
