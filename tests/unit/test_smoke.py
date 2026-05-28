from __future__ import annotations

import subprocess
import sys


def test_cli_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "debug_agent", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout
