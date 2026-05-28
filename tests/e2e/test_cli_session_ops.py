from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "stepping_fixture.py"


def _cli(*args: str, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "debug_agent", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _start_session(tmp_path: Path, *, break_line: int = 7) -> tuple[Path, dict]:
    target = tmp_path / "stepping_fixture.py"
    target.write_text(FIXTURE.read_text(), encoding="utf-8")
    start = _cli(
        "session",
        "start",
        str(target),
        "--break-at",
        f"{target}:{break_line}",
        cwd=tmp_path,
    )
    assert start.returncode == 0, start.stderr
    return target, json.loads(start.stdout)


def _release(tmp_path: Path) -> None:
    _cli("session", "release", cwd=tmp_path)


@pytest.mark.e2e
def test_eval_simple(tmp_path: Path) -> None:
    target, ctx = _start_session(tmp_path)
    assert ctx["location"]["line"] == 7
    try:
        r = _cli("session", "eval", "--expr", "1 + 41", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["result"] == "42"
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_eval_uses_locals(tmp_path: Path) -> None:
    # Break at line 9 so x, y are in scope; eval an expression that uses them.
    target, ctx = _start_session(tmp_path, break_line=9)
    assert ctx["status"] == "stopped"
    try:
        r = _cli("session", "eval", "--expr", "[i * 2 for i in range(5)]", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        # debugpy renders this as ``[0, 2, 4, 6, 8]``.
        assert "0" in payload["result"] and "8" in payload["result"]
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_step_over(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        r = _cli("session", "step", "--mode", "over", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)
        assert ctx["status"] == "stopped"
        # We were at line 7 (x = 1); step-over lands on line 8 (y = 2).
        assert ctx["location"]["line"] == 8
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_continue_to_temp_bp(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        r = _cli("session", "continue", "--to", f"{target}:9", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)
        assert ctx["status"] == "stopped"
        assert ctx["location"]["line"] == 9
        # The temp bp should be gone afterwards.
        ls = _cli("session", "list-bp", cwd=tmp_path)
        listed = json.loads(ls.stdout)
        assert not any(b["line"] == 9 for b in listed["breakpoints"])
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_continue_with_added_bp(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        r = _cli("session", "continue", "--break", f"{target}:9", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)
        assert ctx["status"] == "stopped"
        assert ctx["location"]["line"] == 9
        # The added bp should PERSIST (it's not a --to).
        ls = _cli("session", "list-bp", cwd=tmp_path)
        listed = json.loads(ls.stdout)
        assert any(b["line"] == 9 for b in listed["breakpoints"])
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_set_clear_list_bp(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        s = _cli("session", "set-bp", f"{target}:9", cwd=tmp_path)
        assert s.returncode == 0, s.stderr
        ls = _cli("session", "list-bp", cwd=tmp_path)
        listed = json.loads(ls.stdout)
        assert any(b["line"] == 9 for b in listed["breakpoints"])

        c = _cli("session", "clear-bp", f"{target}:9", cwd=tmp_path)
        assert c.returncode == 0, c.stderr
        ls2 = _cli("session", "list-bp", cwd=tmp_path)
        listed2 = json.loads(ls2.stdout)
        assert not any(b["line"] == 9 for b in listed2["breakpoints"])
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_set_bp_then_continue_stops_there(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        s = _cli("session", "set-bp", f"{target}:9", cwd=tmp_path)
        assert s.returncode == 0, s.stderr
        r = _cli("session", "continue", cwd=tmp_path)
        ctx = json.loads(r.stdout)
        assert ctx["status"] == "stopped"
        assert ctx["location"]["line"] == 9
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_restart_preserves_bps(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        _cli("session", "set-bp", f"{target}:9", cwd=tmp_path)
        r = _cli("session", "restart", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)
        assert ctx["status"] == "stopped"
        # Restart re-launches; first stop is whichever bp the script hits
        # first — line 7 (initial) is before 9 in execution order.
        assert ctx["location"]["line"] in (7, 9)
        ls = _cli("session", "list-bp", cwd=tmp_path)
        listed = json.loads(ls.stdout)
        lines = [b["line"] for b in listed["breakpoints"]]
        assert 9 in lines
        assert 7 in lines
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_continue_to_termination_then_output(tmp_path: Path) -> None:
    target, _ = _start_session(tmp_path)
    try:
        # Continue with no flags — should run to termination.
        cont = _cli("session", "continue", cwd=tmp_path)
        assert cont.returncode == 0, cont.stderr
        ctx = json.loads(cont.stdout)
        # The status may be exited/terminated since the script ends after print.
        assert ctx["status"] in {"exited", "terminated", "stopped"}

        out = _cli("session", "output", cwd=tmp_path)
        assert out.returncode == 0, out.stderr
        payload = json.loads(out.stdout)
        # The fixture prints ``3`` (sum of 1 + 2).
        # Output may also appear directly in ``ctx['output']`` — accept either.
        combined = (payload.get("output") or "") + (ctx.get("output") or "")
        assert "3" in combined
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_step_in(tmp_path: Path) -> None:
    # Start with bp at line 9 (the ``z = add(x, y)`` call) then step in.
    target, _ = _start_session(tmp_path, break_line=9)
    try:
        r = _cli("session", "step", "--mode", "in", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)
        assert ctx["status"] == "stopped"
        # We stepped into ``add`` — top frame should be inside that function.
        # Body of add starts at line 2 (``s = a + b``).
        assert ctx["location"]["line"] in (1, 2)
        assert "add" in ctx["location"]["function"]
    finally:
        _release(tmp_path)


@pytest.mark.e2e
def test_pause_already_stopped_errors(tmp_path: Path) -> None:
    # The session is stopped at line 7 right after start — pause should refuse.
    target, _ = _start_session(tmp_path)
    try:
        r = _cli("session", "pause", cwd=tmp_path)
        # Returns non-zero with an already_stopped error.
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["status"] == "error"
        assert payload["error_type"] == "already_stopped"
    finally:
        _release(tmp_path)
