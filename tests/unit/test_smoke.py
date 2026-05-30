from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version


def test_cli_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "debug_agent", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    # Assert against the installed package version so this never re-stales on a
    # bump — and so it catches cli.py's hardcoded string drifting from pyproject.
    assert version("dbga") in result.stdout
