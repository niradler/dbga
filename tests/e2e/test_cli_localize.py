from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tracebacks"


@pytest.mark.e2e
def test_cli_localize_from_file() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "debug_cli", "localize", "--file", str(FIXTURES / "standard.txt")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "ZeroDivisionError"
    assert len(payload["frames"]) == 2


@pytest.mark.e2e
def test_cli_localize_from_stdin() -> None:
    tb = (FIXTURES / "standard.txt").read_text()
    result = subprocess.run(
        [sys.executable, "-m", "debug_cli", "localize", "--stdin"],
        input=tb,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "ZeroDivisionError"
