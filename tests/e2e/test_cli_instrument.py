from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", "instrument", *args],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
    )


def test_cli_instrument_add_list_revert(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def f():\n    return 1\n")

    add = _run_cli("add", f"{target}:2", "--code", "print('hi')", "--kind", "log", cwd=tmp_path)
    assert add.returncode == 0, add.stderr
    add_payload = json.loads(add.stdout)
    inst_id = add_payload["id"]
    assert target.read_text() == "def f():\n    print('hi')\n    return 1\n"

    listed = _run_cli("list", cwd=tmp_path)
    assert listed.returncode == 0
    listed_payload = json.loads(listed.stdout)
    assert any(i["id"] == inst_id for i in listed_payload["instrumentations"])

    rev = _run_cli("revert", inst_id, cwd=tmp_path)
    assert rev.returncode == 0
    assert target.read_text() == "def f():\n    return 1\n"


def test_cli_instrument_revert_all(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    _run_cli("add", f"{a}:1", "--code", "print('a')", "--kind", "log", cwd=tmp_path)
    rev = _run_cli("revert", "--all", cwd=tmp_path)
    assert rev.returncode == 0
    assert a.read_text() == "x = 1\n"


def test_cli_instrument_outside_cwd_rejected(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    target = outside_dir / "app.py"
    target.write_text("x = 1\n")

    inner = tmp_path / "inner"
    inner.mkdir()
    res = _run_cli("add", f"{target}:1", "--code", "print('x')", "--kind", "log", cwd=inner)
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert payload["status"] == "error"
    assert payload["error_type"] == "safety"


def test_cli_instrument_allow_outside(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    target = outside_dir / "app.py"
    target.write_text("x = 1\n")

    inner = tmp_path / "inner"
    inner.mkdir()
    res = _run_cli(
        "add",
        f"{target}:1",
        "--code",
        "print('x')",
        "--kind",
        "log",
        "--allow-outside",
        cwd=inner,
    )
    assert res.returncode == 0, res.stderr
    assert "print('x')" in target.read_text()


def test_cli_instrument_invalid_target(tmp_path: Path) -> None:
    res = _run_cli("add", "not-a-target", "--code", "x", "--kind", "log", cwd=tmp_path)
    assert res.returncode == 2
    payload = json.loads(res.stdout)
    assert payload["status"] == "error"
