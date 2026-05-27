from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_watch_file(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    log.write_text("info\nERROR boom\nwarn\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "debug_cli",
            "watch",
            "--file",
            str(log),
            "--pattern",
            r"ERROR (\w+)",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["timed_out"] is False
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["groups"] == ["boom"]


def test_cli_watch_cmd() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "debug_cli",
            "watch",
            "--cmd",
            f"{sys.executable} -u -c \"print('ERROR oops')\"",
            "--pattern",
            r"ERROR (\w+)",
            "--timeout",
            "5",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload["matches"]) == 1
