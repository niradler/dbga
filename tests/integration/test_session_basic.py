from __future__ import annotations

from pathlib import Path

import pytest

from debug_cli.core.dap_session import Breakpoint, DapSession

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple_ok.py"


@pytest.mark.integration
def test_session_hits_breakpoint_returns_context() -> None:
    session = DapSession()
    try:
        session.start(script=FIXTURE, breakpoints=[Breakpoint(file=FIXTURE, line=3)])
        ctx = session.wait_for_stop(timeout=10.0)
        assert ctx.status == "stopped"
        assert ctx.reason == "breakpoint"
        assert ctx.location is not None
        assert ctx.location.file.endswith("simple_ok.py")
        assert ctx.location.line == 3
        locals_map = {v.name: v for v in ctx.locals}
        assert "x" in locals_map
        assert locals_map["x"].value == "1"
        # y has not been assigned yet — breakpoint is BEFORE line 3 executes
        assert "y" not in locals_map
        assert len(ctx.stack) >= 1
        assert ctx.stack[0].function == "<module>"
    finally:
        session.release()


@pytest.mark.integration
def test_session_evaluate_in_frame() -> None:
    session = DapSession()
    try:
        session.start(script=FIXTURE, breakpoints=[Breakpoint(file=FIXTURE, line=3)])
        ctx = session.wait_for_stop(timeout=10.0)
        result = session.evaluate("x + 10", frame=ctx.stack[0].frame_id)
        assert result == "11"
    finally:
        session.release()


@pytest.mark.integration
def test_session_continue_to_termination() -> None:
    session = DapSession()
    try:
        session.start(script=FIXTURE, breakpoints=[Breakpoint(file=FIXTURE, line=3)])
        session.wait_for_stop(timeout=10.0)
        terminal = session.continue_(timeout=10.0)
        assert terminal.status in ("exited", "terminated")
    finally:
        session.release()
