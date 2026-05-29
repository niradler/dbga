"""End-to-end Node.js session flow through the real CLI + daemon.

This is the **real user flow** for Node: ``session start --break-at`` →
``eval`` at the stop → ``continue`` → ``release``. It exercises the full
stack the daemon uses, including vscode-js-debug's child-session
delegation (``startDebugging`` reverse-request).

It exists because the original Node integration test only did
launch → stopOnEntry → continue → terminate, which silently skipped two
broken paths: (1) launch-time breakpoints never reached the child session
(they were set on the parent), and (2) ``eval`` resolved its stack frame
from the parent client, so it failed at a child-session breakpoint. A test
that mirrors what a user actually does catches both.

Skips when ``node`` or vscode-js-debug isn't available.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from debug_agent.adapters.node import find_dap_server

BUGGY_JS = """\
function average(nums) {
  const total = nums.reduce((a, b) => a + b, 0);
  return total / nums.length;
}

function main() {
  const data = [10, 20, 30];
  console.log("avg:", average(data));
}

main();
"""


def _js_debug_available() -> bool:
    try:
        find_dap_server()
        return True
    except RuntimeError:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH"),
    pytest.mark.skipif(
        not _js_debug_available(),
        reason="vscode-js-debug not installed",
    ),
]


def _cli(*args: str, cwd: Path, timeout: float = 90.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def test_node_session_breakpoint_eval_flow(tmp_path: Path) -> None:
    """start --break-at → stop at the breakpoint → eval a local → continue → release."""
    target = tmp_path / "buggy.js"
    target.write_text(BUGGY_JS, encoding="utf-8")

    start = _cli(
        "session",
        "start",
        str(target),
        "--break-at",
        f"{target}:3",  # `return total / nums.length;` — nums + total in scope
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    ctx = json.loads(start.stdout)
    try:
        # BUG #1 guard: launch-time breakpoint must bind in the child session.
        # Pre-fix this returned status "terminated" (program ran to completion).
        assert ctx["status"] == "stopped", f"expected stopped, got {ctx!r}"
        assert ctx["location"]["line"] == 3

        # BUG #2 guard: eval must resolve its frame from the child session.
        # Pre-fix this returned {"error_type":"dap","message":"evaluate: request failed"}.
        r = _cli("session", "eval", "--expr", "nums", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        result = payload.get("result", "")
        assert "10" in result and "20" in result and "30" in result, payload

        r2 = _cli("session", "eval", "--expr", "total", cwd=tmp_path)
        assert r2.returncode == 0, r2.stderr
        assert json.loads(r2.stdout)["result"].strip() == "60"

        # Continue to completion.
        cont = _cli("session", "continue", cwd=tmp_path)
        assert cont.returncode == 0, cont.stderr
        assert json.loads(cont.stdout)["status"] in {"terminated", "exited", "stopped"}
    finally:
        _cli("session", "release", cwd=tmp_path)
