from __future__ import annotations

import json
import subprocess
import sys


def test_cli_run_returns_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "debug_agent",
            "run",
            "--timeout",
            "5",
            "--",
            sys.executable,
            "-c",
            "print('hi')",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["exit_code"] == 0
    assert payload["timed_out"] is False
    assert "hi" in payload["stdout"]
