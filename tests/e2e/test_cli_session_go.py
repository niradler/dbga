"""End-to-end Go session flow through the real CLI + daemon.

The **real user flow** for Go: ``session start --break-at`` → ``eval`` at
the stop → ``continue`` → ``release``, driving ``dlv dap``. Mirrors the
Python (``test_cli_session_ops``) and Node (``test_cli_session_node``)
flows so breakpoint + eval coverage is symmetric across all three
languages.

Skips when ``go`` or ``dlv`` isn't on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BUGGY_GO = """\
package main

import "fmt"

func average(nums []int) int {
\ttotal := 0
\tfor _, n := range nums {
\t\ttotal += n
\t}
\treturn total / len(nums)
}

func main() {
\tdata := []int{10, 20, 30}
\tfmt.Println("avg:", average(data))
}
"""

GO_MOD = "module buggy\n\ngo 1.21\n"


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("go") is None, reason="go is not on PATH"),
    pytest.mark.skipif(shutil.which("dlv") is None, reason="delve (dlv) is not on PATH"),
]


def _cli(*args: str, cwd: Path, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def test_go_session_breakpoint_eval_flow(tmp_path: Path) -> None:
    """start --break-at → stop at the breakpoint → eval locals → continue → release."""
    (tmp_path / "buggy.go").write_text(BUGGY_GO, encoding="utf-8")
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    target = tmp_path / "buggy.go"

    start = _cli(
        "session",
        "start",
        str(target),
        "--break-at",
        f"{target}:10",  # `return total / len(nums)` — nums + total in scope
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    ctx = json.loads(start.stdout)
    try:
        assert ctx["status"] == "stopped", f"expected stopped, got {ctx!r}"
        assert ctx["location"]["line"] == 10

        r = _cli("session", "eval", "--expr", "total", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["result"].strip() == "60"

        r2 = _cli("session", "eval", "--expr", "len(nums)", cwd=tmp_path)
        assert r2.returncode == 0, r2.stderr
        assert json.loads(r2.stdout)["result"].strip() == "3"

        cont = _cli("session", "continue", cwd=tmp_path)
        assert cont.returncode == 0, cont.stderr
        assert json.loads(cont.stdout)["status"] in {"terminated", "exited", "stopped"}
    finally:
        _cli("session", "release", cwd=tmp_path)
