"""Every command's error path must emit structured JSON (never a raw traceback)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _cli(
    *args: str, cwd: Path | None = None, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


@pytest.mark.e2e
def test_run_unknown_binary_emits_json(tmp_path: Path) -> None:
    r = _cli(
        "run",
        "--timeout",
        "5",
        "--",
        "definitely-not-a-real-binary-xyz",
        cwd=tmp_path,
    )
    assert r.returncode == 1
    payload = json.loads(r.stdout)
    assert payload["status"] == "error"
    assert "error_type" in payload
    assert payload["error_type"] == "io_error"


@pytest.mark.e2e
def test_session_inspect_unknown_session_emits_json(tmp_path: Path) -> None:
    r = _cli("session", "inspect", "--session", "does-not-exist", cwd=tmp_path)
    # Currently returns 2 for missing-session, but the contract is JSON on stdout.
    assert r.returncode != 0
    payload = json.loads(r.stdout)
    assert payload["status"] == "error"
    assert payload["error_type"] == "no_session"


@pytest.mark.e2e
def test_localize_missing_file_emits_json(tmp_path: Path) -> None:
    r = _cli("localize", "--file", "does-not-exist.txt", cwd=tmp_path)
    assert r.returncode == 1
    payload = json.loads(r.stdout)
    assert payload["status"] == "error"
    assert payload["error_type"] == "io_error"
